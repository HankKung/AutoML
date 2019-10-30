import os
import sys
import PIL
import time
import logging
import datetime

import torch
import torch.backends
import torch.nn as nn
import torch.backends.cudnn
import torch.distributed as dist

from utils.loss import OhemCELoss
from utils.utils import time_for_file
from dataloaders import make_data_loader
from utils.logger import Logger, setup_logger
from utils.optimizer_distributed import Optimizer
from config_utils.retrain_config import config_factory
from retrain_model.build_autodeeplab import Retrain_Autodeeplab
from config_utils.re_train_autodeeplab import obtain_retrain_autodeeplab_args


def main():
    args = obtain_retrain_autodeeplab_args()
    torch.cuda.set_device(args.local_rank)
    cfg = config_factory['resnet_cityscapes']
    if not os.path.exists(cfg.respth):
        os.makedirs(cfg.respth)
    dist.init_process_group(
        backend='nccl',
        init_method='tcp://127.0.0.1:{}'.format(cfg.port),
        world_size=torch.cuda.device_count(),
        rank=args.local_rank
    )
    setup_logger(cfg.respth)
    logger = logging.getLogger()
    rand_seed = args.manualSeed
    # prepare_seed(rand_seed)
    if args.local_rank == 0:
        log_string = 'seed-{}-time-{}'.format(rand_seed, time_for_file())
        train_log_string = 'train_' + log_string
        val_log_string = 'val_' + log_string
        train_logger = Logger(args, log_string)
        train_logger.log('Arguments : -------------------------------')
        for name, value in args._get_kwargs():
            train_logger.log('{:16} : {:}'.format(name, value))
        train_logger.log("Python  version : {}".format(sys.version.replace('\n', ' ')))
        train_logger.log("Pillow  version : {}".format(PIL.__version__))
        train_logger.log("PyTorch version : {}".format(torch.__version__))
        train_logger.log("cuDNN   version : {}".format(torch.backends.cudnn.version()))

        if args.checkname is None:
            args.checkname = 'deeplab-' + str(args.backbone)
    # dataset
    kwargs = {'num_workers': args.workers, 'pin_memory': True, 'drop_last': True}
    train_loader, args.num_classes = make_data_loader(args=args, **kwargs)
#     train_loader = DataLoader(train_dataset, batch_size=cfg.ims_per_gpu, shuffle=False, sampler=sampler,
#                               num_workers=cfg.n_workers, pin_memory=True, drop_last=True)
    # train_dataset = CityScapes(cfg, mode='train')
    # val_dataset = CityScapes(cfg, mode='val')

    # model
    model = Retrain_Autodeeplab(args)
    model.train()
    model.cuda()
    model = nn.parallel.DistributedDataParallel(model, device_ids=[args.local_rank, ], output_device=args.local_rank,
                                                find_unused_parameters = True).cuda()
    n_min = cfg.ims_per_gpu * cfg.crop_size[0] * cfg.crop_size[1] // 16
    criterion = OhemCELoss(thresh=cfg.ohem_thresh, n_min=n_min).cuda()
    max_iteration = int(cfg.max_epoch * len(train_loader))
    #     max_iteration = int(1500000 * 4 // cfg.gpus)
    it = 0
    # optimizer
    optimizer = Optimizer(model, cfg.lr_start, cfg.momentum, cfg.weight_decay, cfg.warmup_steps,
                          cfg.warmup_start_lr, max_iteration, cfg.lr_power)
    if dist.get_rank() == 0:
        print('======optimizer launch successfully , max_iteration {:}!======='.format(max_iteration))

    # train loop
    loss_avg = []
    start_time = glob_start_time = time.time()
    # for it in range(cfg.max_iter):
    for epoch in range(cfg.max_epoch):
        for sample in train_loader:
            im = sample['image'].cuda()
            lb = sample['label'].cuda()
            lb = torch.squeeze(lb, 1)

            optimizer.zero_grad()
            logits = model(im)
            loss = criterion(logits, lb)
            loss.backward()
            optimizer.step()

            loss_avg.append(loss.item())
            # print training log message

            if it % 10000 == 0:
                if dist.get_rank() == 0:
                    torch.save(model.module.state_dict(), os.path.join(
                        cfg.respth, 'iteration_' + str(it) + '_model_final.pth'))

            if it % cfg.msg_iter == 0 and not it == 0 and dist.get_rank() == 0:
                loss_avg = sum(loss_avg) / len(loss_avg)
                lr = optimizer.lr
                ed = time.time()
                t_intv, glob_t_intv = ed - start_time, ed - glob_start_time
                eta = int((max_iteration - it) * (glob_t_intv / it))
                eta = str(datetime.timedelta(seconds=eta))
                msg = ', '.join(['iter: {it}/{max_iteration}', 'lr: {lr:4f}', 'loss: {loss:.4f}', 'eta: {eta}', 'time: {time:.4f}',
                                 ]).format(it=it, max_iteration=max_iteration, lr=lr, loss=loss_avg, time=t_intv, eta=eta)
                #TODO : now the logger.info will error if iter > 350000, so use print haha
                if max_iteration > 350000:
                    logger.info(msg)
                else:
                    print(msg)
                loss_avg = []
            it += 1


if __name__ == "__main__":
    main()
