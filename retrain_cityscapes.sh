CUDA_VISIBLE_DEVICES=0 python train_new_model.py \
 --batch-size 16 --dataset cityscapes --checkname retrain \
 --epoch 4500 --filter_multiplier 20 --backbone resnet \
 --resize 1024 --crop_size 769 \
 --workers 8 --lr 0.05 \
 --use_amp --opt_level O2 \
 --saved-arch-path /home/hankung/AutoML-master/run/cityscapes/new_final/experiment_1 \
 --use_amp --opt_level O2
