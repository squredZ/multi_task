import os
import sys

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(BASE_DIR)

# from public.path import COCO2017_path
from public.detection.dataset.cocodataset import CocoDetection, Resize, RandomFlip, RandomCrop, RandomTranslate, Normalize

import torchvision.transforms as transforms
import torchvision.datasets as datasets


class Config(object):
    log = './log_obj365'  # Path to save log
    checkpoint_path = './checkpoints_obj365'  # Path to store checkpoint model
    resume = './checkpoints_obj365/latest.pth'  # load checkpoint model
    evaluate = None  # evaluate model path
    train_dataset_path = os.path.join('/home/jovyan/data-vol-polefs-1/small_sample/obj365', 'images/train2017')
    val_dataset_path = os.path.join('/home/jovyan/data-vol-polefs-1/small_sample/obj365', 'images/val2017')
    dataset_annotations_path = os.path.join('/home/jovyan/data-vol-polefs-1/small_sample/obj365', 'annotations')

    network = "resnet50_centernet"
    pretrained = False
    num_classes = [365]
    seed = 0
    input_image_size = 512

    
    multi_head = False
    
    #must use at the same time
    #use mlp layer after head
    cls_mlp = False
    #load the params to head2
    load_head = False
    
    #use selayer before head
    selayer = False
    #load the params to head2
    load_head = False
    #use ttf head in centernet head
    use_ttf = False
    pre_model_dir = None
    
    
    use_multi_scale = False
    multi_scale_range = [0.6, 1.4]
    stride = 4

    train_dataset = CocoDetection(image_root_dir=train_dataset_path,
                                  annotation_root_dir=dataset_annotations_path,
                                  set="train2017",
                                  transform=transforms.Compose([
                                      RandomFlip(flip_prob=0.5),
                                      RandomCrop(crop_prob=0.5),
                                      RandomTranslate(translate_prob=0.5),
                                      Normalize(),
                                  ]))

    val_dataset = CocoDetection(image_root_dir=val_dataset_path,
                                annotation_root_dir=dataset_annotations_path,
                                set="val2017",
                                transform=transforms.Compose([
                                    Normalize(),
                                    Resize(resize=input_image_size),
                                ]))

    epochs = 140
    milestones = [90, 120]
    per_node_batch_size = 8
    lr = 5e-4
    num_workers = 16
    print_interval = 100
    apex = True
    sync_bn = False