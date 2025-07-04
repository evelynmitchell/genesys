
# gab.py    # DO NOT CHANGE OR REMOVE THE MAKK HERE, KEEP IT ALWAYS THE FIRST LINE #

import torch
import torch.nn as nn

from model_discovery.model.utils.modules import GABBase # DO NOT CHANGE THIS IMPORT STATEMENT #


class GAB(GABBase):
    def __init__(self,embed_dim: int, block_loc: tuple, device=None,dtype=None,**kwargs): # YOU CAN ADD MORE ARGUMENTS, BUT YOU HAVE TO HAVE embed_dim, device, dtype AS THE ARGUTMENTS #
        factory_kwargs = {"device": device, "dtype": dtype} # remember to pass it to nn layers
        super().__init__(embed_dim, block_loc) # DO NOT CHANGE THIS LINE #
        self.root = RetNet(embed_dim=embed_dim, block_loc=block_loc, kwarg_all=kwargs, **factory_kwargs, **kwargs)

    def _forward(self, X, **Z): 
        X, Z = self.root(X, **Z)
        return X, Z


import torch.nn.functional as F
from model_discovery.model.utils.modules import GAUBase, gau_test, UnitDecl
from torchtune.modules import RMSNorm


class RetNet(GAUBase):

    def __init__(self, embed_dim: int, block_loc: tuple, kwarg_all: dict,
        device=None, dtype=None, norm_eps: float=1e-06, **kwargs):
        self.factory_kwargs = {'device': device, 'dtype': dtype}
        super().__init__(embed_dim, block_loc, kwarg_all)
        self.hidden_size = embed_dim
        self.attn_norm = RMSNorm(self.hidden_size, eps=norm_eps).to(device=
            device, dtype=dtype)
        self.attn = MultiScaleRetention(embed_dim=self.embed_dim, block_loc
            =self.block_loc, kwarg_all=self.kwarg_all, **self.
            factory_kwargs, **self.kwarg_all)
        self.mlp_norm = RMSNorm(self.hidden_size, eps=norm_eps).to(device=
            device, dtype=dtype)
        self.mlp = RetNetMLP(embed_dim=self.embed_dim, block_loc=self.
            block_loc, kwarg_all=self.kwarg_all, **self.factory_kwargs, **
            self.kwarg_all)

    def _forward(self, X, **Z):
        hidden_states = self.attn_norm(X)
        X = self.attn(hidden_states, **Z)[0] + X
        hidden_states = self.mlp_norm(X)
        X = self.mlp(hidden_states, **Z)[0] + X
        return X, Z


CHILDREN_DECLARATIONS = [UnitDecl(unitname='MultiScaleRetention',
    requirements='', inputs=['X'], outputs=['Y']), UnitDecl(unitname=
    'RetNetMLP', requirements='', inputs=['X'], outputs=['Y'])]

import torch.nn.functional as F
from transformers.activations import ACT2FN
from einops import rearrange, repeat
from torchtune.modules import RotaryPositionalEmbeddings, RMSNorm


class MultiScaleRetention(GAUBase):

    def __init__(self, embed_dim: int, block_loc: tuple, kwarg_all: dict,
        device=None, dtype=None, hidden_size=None, num_heads: int=8,
        norm_eps: float=1e-05, **kwargs):
        self.factory_kwargs = {'device': device, 'dtype': dtype}
        super().__init__(embed_dim, block_loc, kwarg_all)
        hidden_size = hidden_size if hidden_size is not None else embed_dim
        self.hidden_size = hidden_size
        self.num_heads = num_heads
        self.num_kv_heads = num_heads
        self.num_kv_groups = self.num_heads // self.num_kv_heads
        self.key_dim = hidden_size
        self.value_dim = hidden_size * 2
        self.key_dim_per_group = self.key_dim // self.num_kv_groups
        self.value_dim_per_group = self.value_dim // self.num_kv_groups
        assert self.key_dim % num_heads == 0, f'key dim must be divisible by num_heads of {num_heads}'
        assert self.value_dim % num_heads == 0, f'value dim must be divisible by num_heads of {num_heads}'
        self.head_qk_dim = self.key_dim // num_heads
        self.head_v_dim = self.value_dim // num_heads
        self.q_proj = nn.Linear(hidden_size, self.key_dim, bias=False,
            device=device, dtype=dtype)
        self.k_proj = nn.Linear(hidden_size, self.key_dim_per_group, bias=
            False, device=device, dtype=dtype)
        self.v_proj = nn.Linear(hidden_size, self.value_dim_per_group, bias
            =False, device=device, dtype=dtype)
        self.g_proj = nn.Linear(hidden_size, self.value_dim, bias=False,
            device=device, dtype=dtype)
        self.o_proj = nn.Linear(self.value_dim, hidden_size, bias=False,
            device=device, dtype=dtype)
        self.g_norm = RMSNorm(self.head_v_dim, eps=norm_eps).to(device=
            device, dtype=dtype)
        self.gate_fn = ACT2FN['swish']
        self.rotary = RotaryPositionalEmbeddings(dim=self.head_qk_dim).to(
            device=device, dtype=dtype)
        self.apply(self._initialize_weights)

    def _initialize_weights(self, module: nn.Module):
        if getattr(module, '_is_hf_initialized', False):
            return
        if isinstance(module, nn.Linear):
            nn.init.xavier_uniform_(module.weight, gain=2 ** -2.5)
            if module.bias is not None:
                nn.init.zeros_(module.bias)
        module._is_hf_initialized = True

    def naive_retention(self, q, k, v):
        orig_type = q.dtype
        q, k, v = q.float(), k.float(), v.float()
        _, n_heads, seq_len, d_head = q.shape
        s = (1 - q.new_tensor(2.0, dtype=torch.float).pow(-5.0 - q.
            new_tensor(range(n_heads), dtype=torch.float))).log2()
        n = q.new_tensor(range(seq_len), dtype=torch.float)
        n = torch.exp2((n.unsqueeze(-1) - n) * s.view(-1, 1, 1)) * n.unsqueeze(
            -1).ge(n)
        s = torch.einsum('bhqd,bhkd,hqk->bhqk', q * d_head ** -0.5, k, n.to
            (q.dtype))
        o = torch.einsum('bhqk,bhkd->bhqd', s, v)
        return o.to(orig_type)

    def _forward(self, X, **Z):
        q = self.q_proj(X)
        k = self.k_proj(X)
        v = self.v_proj(X)
        q = rearrange(q, '... (h d) -> ... h d', h=self.num_heads)
        k = rearrange(k, '... (h d) -> ... h d', h=self.num_kv_heads)
        q = self.rotary(q)
        k = self.rotary(k)
        q = q.transpose(1, 2)
        if self.num_kv_groups > 1:
            k = repeat(k, 'b t h d -> b (h g) t d', h=self.num_kv_heads, g=
                self.num_kv_groups)
            v = repeat(v, 'b t (h d) -> b (h g) t d', h=self.num_kv_heads,
                g=self.num_kv_groups)
        else:
            k, v = rearrange(k, 'b t h d -> b h t d'), rearrange(v,
                'b t (h d) -> b h t d', h=self.num_kv_heads)
        o = self.naive_retention(q, k, v)
        o = rearrange(o, 'b h l d -> b l h d')
        g = self.g_proj(X)
        o = rearrange(self.g_norm(o), 'b l h d -> b l (h d)')
        o = o * self.gate_fn(g)
        o = self.o_proj(o)
        return o


CHILDREN_DECLARATIONS = []

import torch.nn.functional as F
from transformers.activations import ACT2FN


class RetNetMLP(GAUBase):

    def __init__(self, embed_dim: int, block_loc: tuple, kwarg_all: dict,
        device=None, dtype=None, hidden_size=None, **kwargs):
        self.factory_kwargs = {'device': device, 'dtype': dtype}
        super().__init__(embed_dim, block_loc, kwarg_all)
        hidden_size = hidden_size if hidden_size is not None else embed_dim
        self.hidden_size = hidden_size
        hidden_ratio = 2
        intermediate_size = int(hidden_size * hidden_ratio * 2 / 3)
        intermediate_size = 256 * ((intermediate_size + 256 - 1) // 256)
        self.hidden_ratio = hidden_ratio
        self.intermediate_size = intermediate_size
        self.gate_proj = nn.Linear(self.hidden_size, self.intermediate_size *
            2, bias=False, device=device, dtype=dtype)
        self.down_proj = nn.Linear(self.intermediate_size, self.hidden_size,
            bias=False, device=device, dtype=dtype)
        self.act_fn = ACT2FN['swish']

    def _forward(self, X, **Z):
        y = self.gate_proj(X)
        gate, y = y.chunk(2, -1)
        z = self.act_fn(gate) * y
        x = self.down_proj(z)
        return x


CHILDREN_DECLARATIONS = []


gab_config = {'hidden_size': None, 'num_heads': 8, 'norm_eps': 1e-06}