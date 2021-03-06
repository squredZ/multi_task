import os
import sys
import math
import numpy as np
from fvcore.nn import c2_xavier_fill

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))
sys.path.append(BASE_DIR)

from public.path import pretrained_models_path
from config.config import Config

from public.detection.models.backbone import ResNetBackbone
from public.detection.models.head import FCOSClsRegCntHead
from public.detection.models.anchor import FCOSPositions

import torch
import torch.nn as nn
import torch.nn.functional as F


__all__ = [
    'resnet18_yolof',
    'resnet34_yolof',
    'resnet50_yolof',
    'resnet101_yolof',
    'resnet152_yolof',
]

model_urls = {
    'resnet18_yolof':
    '/home/jovyan/data-vol-polefs-1/pretrained_models/resnet/resnet18-epoch100-acc70.316.pth',
    'resnet34_yolof':
    'empty',
    'resnet50_yolof':
    '/home/jovyan/data-vol-polefs-1/pretrained_models/resnet/resnet50-epoch100-acc76.512.pth',
    'resnet101_yolof':
    '/home/jovyan/data-vol-polefs-1/pretrained_models/resnet/resnet101-epoch100-acc77.724.pth',
    'resnet152_yolof':
    'empty',
}


class Bottleneck(nn.Module):

    def __init__(self,
                 in_channels: int = 512,
                 mid_channels: int = 128,
                 dilation: int = 1):
        super(Bottleneck, self).__init__()
        self.conv1 = nn.Sequential(
            nn.Conv2d(in_channels, mid_channels, kernel_size=1, padding=0),
            nn.BatchNorm2d(mid_channels),
            nn.ReLU(inplace=True)
        )
        self.conv2 = nn.Sequential(
            nn.Conv2d(mid_channels, mid_channels,
                      kernel_size=3, padding=dilation, dilation=dilation),
            nn.BatchNorm2d(mid_channels),
            nn.ReLU(inplace=True)
        )
        self.conv3 = nn.Sequential(
            nn.Conv2d(mid_channels, in_channels, kernel_size=1, padding=0),
            nn.BatchNorm2d(in_channels),
            nn.ReLU(inplace=True)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        identity = x
        out = self.conv1(x)
        out = self.conv2(out)
        out = self.conv3(out)
        out = out + identity
        return out

class DilatedEncoder(nn.Module):
    """
    Dilated Encoder for YOLOF.
    This module contains two types of components:
        - the original FPN lateral convolution layer and fpn convolution layer,
          which are 1x1 conv + 3x3 conv
        - the dilated residual block
    """

    def __init__(self, in_channels, encoder_channels):
        super(DilatedEncoder, self).__init__()
        # fmt: off
        self.in_channels = in_channels
        self.encoder_channels = encoder_channels
        self.block_mid_channels = 128
        self.num_residual_blocks = 4
        self.block_dilations = [2, 4, 6, 8]
        # fmt: on

        # init
        self._init_layers()
        self._init_weight()

    def _init_layers(self):
        self.lateral_conv = nn.Conv2d(self.in_channels,
                                      self.encoder_channels,
                                      kernel_size=1)
        self.lateral_norm = nn.BatchNorm2d(self.encoder_channels)
        self.fpn_conv = nn.Conv2d(self.encoder_channels,
                                  self.encoder_channels,
                                  kernel_size=3,
                                  padding=1)
        self.fpn_norm = nn.BatchNorm2d(self.encoder_channels)
        encoder_blocks = []
        for i in range(self.num_residual_blocks):
            dilation = self.block_dilations[i]
            encoder_blocks.append(
                Bottleneck(
                    self.encoder_channels,
                    self.block_mid_channels,
                    dilation=dilation
                )
            )
        self.dilated_encoder_blocks = nn.Sequential(*encoder_blocks)

    def _init_weight(self):
        c2_xavier_fill(self.lateral_conv)
        c2_xavier_fill(self.fpn_conv)
        for m in [self.lateral_norm, self.fpn_norm]:
            nn.init.constant_(m.weight, 1)
            nn.init.constant_(m.bias, 0)
        for m in self.dilated_encoder_blocks.modules():
            if isinstance(m, nn.Conv2d):
                nn.init.normal_(m.weight, mean=0, std=0.01)
                if hasattr(m, 'bias') and m.bias is not None:
                    nn.init.constant_(m.bias, 0)

            if isinstance(m, (nn.GroupNorm, nn.BatchNorm2d, nn.SyncBatchNorm)):
                nn.init.constant_(m.weight, 1)
                nn.init.constant_(m.bias, 0)

    def forward(self, feature: torch.Tensor):
        out = self.lateral_norm(self.lateral_conv(feature))
        out = self.fpn_norm(self.fpn_conv(out))
        out = self.dilated_encoder_blocks(out)
        return out


    
    
class UP_layer(nn.Module):
    def __init__(self, in_channels, out_channels):
        super(UP_layer, self ).__init__() 
        self.layer = nn.Sequential(
        #                 DeformableConv2d(in_channels,
        #                                  out_channels,
        #                                  kernel_size=(3, 3),
        #                                  stride=1,
        #                                  padding=1,
        #                                  groups=1,
        #                                  bias=False)
                        nn.Conv2d(in_channels,
                                 out_channels,
                                 kernel_size=1,
                                 stride=1,
                                 padding=0,
                                 bias=False),
                    nn.BatchNorm2d(out_channels),
                    nn.ReLU(inplace=True),
                    nn.ConvTranspose2d(in_channels=out_channels,
                                           out_channels=out_channels,
                                           kernel_size=4,
                                           stride=2,
                                           padding=1,
                                           output_padding=0,
                                           bias=False),
                    nn.BatchNorm2d(out_channels),
                    nn.ReLU(inplace=True)
        )
        for m in self.layer.modules():
            if isinstance(m, nn.ConvTranspose2d):
                w = m.weight.data
                f = math.ceil(w.size(2) / 2)
                c = (2 * f - 1 - f % 2) / (2. * f)
                for i in range(w.size(2)):
                    for j in range(w.size(3)):
                        w[0, 0, i, j] = (1 - math.fabs(i / f - c)) * (
                            1 - math.fabs(j / f - c))
                for c in range(1, w.size(0)):
                    w[c, 0, :, :] = w[0, 0, :, :]
            elif isinstance(m, nn.Conv2d):
                nn.init.normal_(m.weight, std=0.001)
        
    def forward(self, x):
        out = self.layer(x)
        return out

class ShortCut(nn.Module):
    def __init__(self, in_channels, out_channels):
        super(ShortCut, self).__init__()
        self.conv1 = nn.Conv2d(in_channels,
                             out_channels,
                             kernel_size=1,
                             stride=1,
                             padding=0,
                             bias=False)
        nn.init.normal_(self.conv1.weight, std=0.001)

    def forward(self, x):
        return self.conv1(x)
                    
class YOLOF(nn.Module):
    def __init__(self, resnet_type, config):
        super(YOLOF, self).__init__()
        self.backbone = ResNetBackbone(resnet_type=resnet_type)
        expand_ratio = {
            "resnet18": 1,
            "resnet34": 1,
            "resnet50": 4,
            "resnet101": 4,
            "resnet152": 4
        }
        C5_inplanes = int(512 * expand_ratio[resnet_type])
        self.inplanes = C5_inplanes
        self.up_layers = []
        self.shortcuts = []
        
        self.num_layers = config.num_layers
        self.ttf_out_channels = config.ttf_out_channels
        for i in range(self.num_layers):
            self.up_layers.append(UP_layer(self.inplanes, self.ttf_out_channels[i]))
            self.shortcuts.append(ShortCut(int(C5_inplanes/(2**(i+1))),
                                         self.ttf_out_channels[i]))
            self.inplanes = self.ttf_out_channels[i]
        self.dila_encoder = DilatedEncoder(self.inplanes, config.yolof_encoder_channels)
        self.multi_task = config.multi_task

        self.num_classes = config.num_classes
        

        self.clsregcnt_head = FCOSClsRegCntHead(config.yolof_encoder_channels,
                                                self.num_classes,
                                                num_layers=4,
                                                prior=config.prior,
                                                use_gn=config.use_GN_head,
                                                cnt_on_reg=config.cnt_on_reg)
        
        self.strides = torch.tensor(config.strides, dtype=torch.float)
        self.positions = FCOSPositions(self.strides)
        self.scale = torch.tensor(1,dtype=torch.float)
        
    def forward(self, inputs):
        self.batch_size, _, _, _ = inputs.shape
        device = inputs.device
        out = self.backbone(inputs)
        del inputs
        c = out[-1]
        for i in range(self.num_layers):
            c = self.up_layers[i].to(device)(c)
            c = c + self.shortcuts[i].to(device)(out[-2-i])

        features = [self.dila_encoder(c)]
        del c


        self.fpn_feature_sizes = []
        cls_heads, reg_heads, center_heads = [], [], []
        for feature in features:
            self.fpn_feature_sizes.append([feature.shape[3], feature.shape[2]])

            if self.multi_task:
                cls_outs, reg_outs, center_outs = self.clsregcnt_head2(feature)
            else:
                cls_outs, reg_outs, center_outs = self.clsregcnt_head(feature)

            # [N,num_classes,H,W] -> [N,H,W,num_classes]
            cls_outs = cls_outs.permute(0, 2, 3, 1).contiguous()
            cls_heads.append(cls_outs)
            # [N,4,H,W] -> [N,H,W,4]
            reg_outs = reg_outs.permute(0, 2, 3, 1).contiguous()
            reg_outs = reg_outs * torch.exp(self.scale)
            reg_heads.append(reg_outs)
            # [N,1,H,W] -> [N,H,W,1]
            center_outs = center_outs.permute(0, 2, 3, 1).contiguous()
            center_heads.append(center_outs)

        del features

        self.fpn_feature_sizes = torch.tensor(
            self.fpn_feature_sizes).to(device)

        batch_positions = self.positions(self.batch_size,
                                         self.fpn_feature_sizes)

        # if input size:[B,3,640,640]
        # features shape:[[B, 256, 80, 80],[B, 256, 40, 40],[B, 256, 20, 20],[B, 256, 10, 10],[B, 256, 5, 5]]
        # cls_heads shape:[[B, 80, 80, 80],[B, 40, 40, 80],[B, 20, 20, 80],[B, 10, 10, 80],[B, 5, 5, 80]]
        # reg_heads shape:[[B, 80, 80, 4],[B, 40, 40, 4],[B, 20, 20, 4],[B, 10, 10, 4],[B, 5, 5, 4]]
        # center_heads shape:[[B, 80, 80, 1],[B, 40, 40, 1],[B, 20, 20, 1],[B, 10, 10, 1],[B, 5, 5, 1]]
        # batch_positions shape:[[B, 80, 80, 2],[B, 40, 40, 2],[B, 20, 20, 2],[B, 10, 10, 2],[B, 5, 5, 2]]

        return cls_heads, reg_heads, center_heads, batch_positions


def _yolof(arch, pretrained, **kwargs):
    model = YOLOF(arch, **kwargs)
    # only load state_dict()
    if pretrained:
        pretrained_models = torch.load(model_urls[arch + "_yolof"],
                                       map_location=torch.device('cpu'))
        # del pretrained_models['cls_head.cls_head.8.weight']
        # del pretrained_models['cls_head.cls_head.8.bias']

        # only load state_dict()
        model.load_state_dict(pretrained_models, strict=False)

    return model


def resnet18_yolof(pretrained=False, **kwargs):
    return _yolof('resnet18', pretrained, **kwargs)


def resnet34_yolof(pretrained=False, **kwargs):
    return _yolof('resnet34', pretrained, **kwargs)


def resnet50_yolof(pretrained=False, **kwargs):
    return _yolof('resnet50', pretrained, **kwargs)


def resnet101_yolof(pretrained=False, **kwargs):
    return _yolof('resnet101', pretrained, **kwargs)


def resnet152_yolof(pretrained=False, **kwargs):
    return _yolof('resnet152', pretrained, **kwargs)


if __name__ == '__main__':
    net = YOLOF(resnet_type="resnet50", config=Config)
    # for item in net.named_modules():
    #     print(item)
    image_h, image_w = 667, 667
    cls_heads, reg_heads, center_heads, batch_positions = net(
        torch.autograd.Variable(torch.randn(3, 3, image_h, image_w)))
    annotations = torch.FloatTensor([[[113, 120, 183, 255, 5],
                                      [13, 45, 175, 210, 2]],
                                     [[11, 18, 223, 225, 1],
                                      [-1, -1, -1, -1, -1]],
                                     [[-1, -1, -1, -1, -1],
                                      [-1, -1, -1, -1, -1]]])

    print("1111", cls_heads[0].shape, reg_heads[0].shape,
          center_heads[0].shape, batch_positions[0].shape)