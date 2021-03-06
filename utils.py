from collections import OrderedDict
import datetime
import os

import torch
import torch.nn as nn
import random

from torch.utils.data import Dataset
import numpy as np

KST = datetime.timezone(datetime.timedelta(hours=9))


class CosineLoss(nn.Module):
    def __init__(self):
        super(CosineLoss, self).__init__()
        self.cos = nn.CosineSimilarity(dim=0)

    def forward(self, feats):
        loss = []
        num_nodes = feats.size(0)
        for i in range(num_nodes):
            for j in range(i+1, num_nodes):
                loss.append(self.cos(feats[i], feats[j]))

        loss = (1-torch.stack(loss)).mean()
        return loss


def now_kst():
    return datetime.datetime.now(tz=KST).strftime('%Hh%Mm%Ss')


def get_dirname(mode):
    t = datetime.datetime.now(tz=KST).strftime('%m%d_%H%M')
    dname = f'./backup/{mode}_{t}'
    if not os.path.exists(dname):
        os.makedirs(dname)
    return dname


def load_embedding(embedding_path, requires_grad=None, device=None):
    state = torch.load(embedding_path, device)

    mode = 'skipgram'
    if 'u_embedding.weight' in state:
        weight = state['u_embedding.weight']
        state = OrderedDict()
        state['weight'] = weight
    elif 'u_embeddings.weight' in state:
        weight = state['u_embeddings.weight']
        state = OrderedDict()
        state['weight'] = weight
    else:
        mode = 'symmetric'
        weight = state['embedding.weight']
        state = OrderedDict()
        state['weight'] = weight

    vocabulary_size, embedding_dim = state['weight'].shape
    model = nn.Embedding(vocabulary_size, embedding_dim, sparse=True)
    model.load_state_dict(state)
    model.requires_grad_(bool(requires_grad))
    return mode, model
