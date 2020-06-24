"""
Note:
  'classifier.pth' and 'log.txt' are saved under ./backup/.../ directory.
  The argument parser of this script is automatically generated by
  docopt package using this help message itself.

Usage:
  train_classifier.py (--embedding <str>) (--lstm | --deepset) [options]
  train_classifier.py (-h | --help)

Options:
  --embedding <str>     Path for embedding.pth (required)
  --no-train-embedding  When set, re-train embedding
  --handle-foreign      When set, make all foreign authors to have the same idx. If there are more than one foreign authors, only one idx remains.

  --lstm                When set, use bidirectional LSTM aggregator
  --deepset             When set, use DeepSet aggregator
  --hidden <int>        Hidden size         [default: 256]
  --dropout <float>     Dropout rate        [default: 0.5]
  --enable-all-pools    (DeepSet only option) enable all poolings

  -b --batch <int>      Batch size          [default: 100]
  --emb-lr <float>      Learning rate for embedding network [default: 1e-3]
  --lr <float>          Learning rate       [default: 1e-3]
  --weight-decay <float>    Weight Decay    [default: 1e-4]
  -e --epochs <int>     Epochs              [default: 10]
  --ratio <float>       Train validation split ratio    [default: 0.8]
  --use-paper-author    Use paper_author.txt in addition to query_public.txt
  --oversample-false-collabs    Oversample false collabs. Only effective when used with --use-paper-author.

  -s --seed <int>       Random seed         [default: 0]
  --dirname <str>       Directory name to save trained files [default: None]
  --device <int>        Cuda device         [default: 0]

  -h --help             Show this screen
"""

import os

# parsing library for cmd options and arguments https://github.com/docopt/docopt
from docopt import docopt
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader
from tqdm import tqdm

from data import QueryDataset
from model import Classifier
from utils import get_dirname, now_kst, load_embedding


def train_classifier(train_loader, valid_loader, classifier,
                     optimizers, device, epoch, batch_size, logdir=None):
    avg_loss = 0
    loss = 0
    buckets = {}
    train_correct = 0

    # NOTE: train_loader is supposed to have batch size 1
    for i, (collab, label) in enumerate(train_loader):
        # Do bucketing to allow batch size to be bigger than 1
        if (i+1) % batch_size != 0 and (i+1) != len(train_loader):
            seq_len = collab.shape[1]
            if seq_len not in buckets:
                buckets[seq_len] = ([], [])
            collabs_list, labels_list = buckets[seq_len]
            collabs_list.append(collab)
            labels_list.append(label)
        else:
            [optim.zero_grad() for optim in optimizers]
            for collabs_list, labels_list in buckets.values():
                collabs = torch.cat(collabs_list, dim=0)
                labels = torch.cat(labels_list, dim=0)
                score = classifier(collabs.to(device))
                # L2 loss
                step_loss = (labels[:, None].to(device) - score).pow(2).sum()
                loss += step_loss
                avg_loss += step_loss.item()
                # Measuer accuracy
                with torch.no_grad():
                    correct = (labels[:, None] == score.cpu().round()).sum()
                    train_correct += correct.item()
            loss /= batch_size
            loss.backward()

            [optim.step() for optim in optimizers]
            loss = 0
            buckets = {}

        if (i+1) % 50000 == 0 or (i+1) == len(train_loader):
            correct = 0
            classifier.eval()
            for collabs, labels in valid_loader:
                score = classifier(collabs.to(device)).round()
                correct += (score.cpu() == labels).item()

            acc = (correct / len(valid_loader)) * 100
            train_acc = (train_correct / (i+1)) * 100
            classifier.train()

            _avg_loss = avg_loss / (i+1)
            log_msg = f'Epoch {epoch+1:d} | Avg Loss: {_avg_loss:.6f} | Train Acc: '\
                    f'{train_acc:.2f}% | Val Acc: {acc:.2f}% | {now_kst()}'
            path = os.path.join(logdir, 'log.txt')
            with open(path, 'a') as f:
                f.write(log_msg + '\n')

    return avg_loss, train_acc, acc


def main():
    args = docopt(__doc__)
    train_embedding = not args['--no-train-embedding']
    handle_foreign = args['--handle-foreign']
    enable_all_pools = args['--enable-all-pools']

    np.random.seed(int(args['--seed']))
    torch.manual_seed(int(args['--seed']))
    torch.cuda.manual_seed_all(int(args['--seed']))

    hidden = int(args['--hidden'])
    dropout = float(args['--dropout'])
    batch_size    = int(args['--batch'])
    lr     = float(args['--lr'])
    emb_lr     = float(args['--emb-lr'])
    weight_decay = float(args['--weight-decay'])
    epochs = int(args['--epochs'])
    device = torch.device(int(args['--device']))
    print(f"{device} will be used")
    ratio  = float(args['--ratio'])
    dname = args['--dirname']

    train_dset = QueryDataset(split='train', ratio=ratio,
                              equally_handle_foreign_authors=handle_foreign,
                              use_paper_author=args['--use-paper-author'],
                              oversample_false_collabs=args['--oversample-false-collabs'])
    valid_dset = QueryDataset(split='valid', ratio=ratio,
                              equally_handle_foreign_authors=handle_foreign)
    train_loader = DataLoader(train_dset, batch_size=1, num_workers=1, shuffle=True)
    valid_loader = DataLoader(valid_dset, batch_size=1, num_workers=1, shuffle=False)

    embedding_mode, embedding = load_embedding(
        args['--embedding'], train_embedding, device)
    classifier = Classifier(embedding, hidden, dropout, args['--deepset'],
                            equally_handle_foreign_authors=handle_foreign,
                            enable_all_pools=enable_all_pools)

    if torch.cuda.is_available():
        classifier.to(device)

    emb_params = set(embedding.parameters())
    cls_params = set(classifier.parameters()).difference(emb_params)

    optimizer1 = optim.SparseAdam(emb_params, lr=emb_lr)
    optimizer2 = optim.Adam(cls_params, lr=lr, weight_decay=weight_decay)

    train_embedding = 'on' if train_embedding else 'off'
    if dname == 'None':
        mode = f'{classifier.savename}_emb-{embedding_mode}'\
               f'_trainemb-{train_embedding}'
        dname = get_dirname(mode)
    else:
        os.makedirs(dname, exist_ok=True)
    path = os.path.join(dname, 'log.txt')
    with open(path, 'a') as f:
        f.write(repr(args) + '\n')
    backup_path = os.path.join(dname, 'classifier.pth')

    # TODO: Add checkpoint training feature

    pbar = tqdm(total=epochs, initial=0,
                bar_format="{desc:<5}{percentage:3.0f}%|{bar:10}{r_bar}")
    best_acc = 0
    for epoch in range(epochs):
        avg_loss, train_acc, val_acc = train_classifier(
            train_loader, valid_loader, classifier,
            [optimizer1, optimizer2], device, epoch, batch_size, dname)
        if val_acc > best_acc:
            torch.save(classifier.state_dict(), backup_path)
        pbar.set_description(
            f'Train Loss: {avg_loss:.6f}, Train Acc:{train_acc:.2f} Valid Acc: {val_acc:.2f}%')
        pbar.update(1)

if __name__ == '__main__':
    main()
