from __future__ import annotations
from typing import Tuple

import torch
from torch import nn, einsum, Tensor
import torch.nn.functional as F
from torch.cuda.amp import autocast
from torch.nn import Module, ModuleList

from einops import rearrange, repeat

from beartype import beartype

from ring_attention_pytorch.ring import (
    is_distributed,
    get_rank,
    get_world_size
)

from ring_attention_pytorch.distributed import (
    split_by_rank,
    AllGather
)

# helper functions

def exists(v):
    return v is not None

def default(v, d):
    return v if exists(v) else d

def cast_tuple(t, length = 1):
    return t if isinstance(t, tuple) else ((t,) * length)

def divisible_by(num, den):
    return (num % den) == 0

def softclamp(t, value):
    return (t / value).tanh() * value

@beartype
def default_attention(
    q: Tensor,
    k: Tensor,
    v: Tensor,
    mask: Tensor | None = None,
    causal: bool = False,
    softclamp_qk_sim: bool = False,
    softclamp_value: float = 50.
):
    device = q.device
    q = q * (q.shape[-1] ** -0.5)

    mask_value = -torch.finfo(q.dtype).max

    # account for grouped query attention

    heads, kv_heads = q.shape[-2], k.shape[-2]
    assert divisible_by(heads, kv_heads)
    q_head_groups = heads // kv_heads

    k, v = map(lambda t: repeat(t, '... h d -> ... (g h) d', g = q_head_groups), (k, v))

    # similarity

    sim = einsum('b i h d, b j h d -> b h i j', q, k)

    # softclamp

    if softclamp_qk_sim:
        sim = softclamp(sim, softclamp_value)

    # masking

    if causal:
        i, j = sim.shape[-2:]
        causal_mask = torch.ones((i, j), dtype = torch.bool, device = device).triu(j - i + 1)
        sim = torch.where(causal_mask, mask_value, sim)

    elif exists(mask):
        mask = rearrange(mask, 'b j -> b 1 1 j')
        sim = sim.masked_fill(~mask, mask_value)

    # attend

    attn = sim.softmax(dim = -1)

    # aggregate

    out = einsum('b h i j, b j h d -> b i h d', attn, v)

    return out

# rotary embeddings with modifications to support striped attention

class RingRotaryEmbedding(Module):
    @beartype
    def __init__(
        self,
        dim,
        ring: bool = False,
        striped: bool = False,
        buckets: int = 1,        # in striped attention with flash buckets > 1, one needs to specify the number of buckets per machine
        theta = 10000
    ):
        super().__init__()
        self.ring = ring
        self.striped = striped
        self.buckets = buckets

        inv_freq = theta ** -(torch.arange(0, dim, 2).float() / dim)
        self.register_buffer('inv_freq', inv_freq)

    @property
    def device(self):
        return self.inv_freq.device

    @property
    def is_cuda(self):
        return self.inv_freq.is_cuda

    @autocast(enabled = False)
    @beartype
    def forward(
        self,
        seq_len: int
    ):
        device = self.device

        pos = None

        if self.ring:
            if self.striped:
                buckets = 1 if self.is_cuda else self.buckets
                ring_stride = get_world_size() * buckets

                pos = torch.arange(seq_len // buckets, device = device)
                pos = repeat(pos, 'n -> n b', b = buckets)

                pos = pos * ring_stride
                pos += torch.arange(buckets, device = device) + (get_rank() * buckets)
                pos = rearrange(pos, 'n b -> (b n)')

            else:
                pos = torch.arange(seq_len, device = device)
                pos += seq_len * get_rank()
        else:
            pos = torch.arange(seq_len, device = device)

        pos = pos.type_as(self.inv_freq)
        freqs = einsum('i , j -> i j', pos, self.inv_freq)
        return torch.cat((freqs, freqs), dim = -1)

def rotate_half(x):
    x1, x2 = x.chunk(2, dim = -1)
    return torch.cat((-x2, x1), dim=-1)

@autocast(enabled = False)
def apply_rotary_pos_emb(pos, t):
    pos = rearrange(pos, 'n d -> n 1 d')
    return t * pos.cos() + rotate_half(t) * pos.sin()

# batch to sequence sharding and back

def pad_at_dim(
    t: Tensor,
    pad: Tuple[int, int],
    *,
    dim = -1,
    value = 0.
):
    dims_from_right = (- dim - 1) if dim < 0 else (t.ndim - dim - 1)
    zeros = ((0, 0) * dims_from_right)
    return F.pad(t, (*zeros, *pad), value = value)

def pad_to_multiple(
    x: Tensor,
    length: int,
    pad_value = 0
):
    seq_len = x.shape[1]
    remainder = seq_len % length

    if remainder == 0:
        return x, 0

    pad_length = length - remainder
    return pad_at_dim(x, (0, pad_length), value = pad_value, dim = 1), pad_length

def maybe_pad_seq_and_mask(
    x: Tensor,
    mask: Tensor | None,
    seq_size: int
):
    orig_x, device, shape = x, x.device, x.shape[:2]
    seq_len = shape[-1]

    # auto pad sequence and mask, as ring passing makes assumption tensor is all same shape

    x, pad_length = pad_to_multiple(x, seq_size)

    if pad_length == 0:
        return x, mask

    if not exists(mask):
        mask = torch.ones(shape, device = device).bool()

    mask, _ = pad_to_multiple(mask, seq_size, pad_value = False)

    return x, mask

def sharded_batch_to_sharded_seq(
    x: Tensor,
    mask: Tensor | None,
    seq_size: int
):
    assert is_distributed()

    # all gather across batch

    all_gather = AllGather(dim = 0)

    x, sizes = all_gather(x)

    if exists(mask):
        mask, _ = all_gather(mask)

    # first make sure world size is divisible by the sequence size

    world_size = get_world_size()

    total_split_seq = x.shape[1] // seq_size

    assert divisible_by(world_size, total_split_seq)

    num_sharded_batches = world_size // total_split_seq

    x = rearrange(x, '(b s) n ... -> b (s n) ...', s = num_sharded_batches)

    # then split sequence across machines

    x = x.split(seq_size, dim = 1)

    x, _ = split_by_rank(x)

    if exists(mask):
        mask = rearrange(mask, '(b s) n -> b (s n)', s = num_sharded_batches)
        mask = mask.split(seq_size, dim = -1)
        mask, _ = split_by_rank(mask)

    return (x, mask), sizes, num_sharded_batches

def sharded_seq_to_sharded_batch(
    logits: Tensor,
    sizes,
    num_sharded_batches = 1
):
    all_gather = AllGather(dim = -2) # all gather across sequence

    logits, _ = all_gather(logits)

    logits = rearrange(logits, 'b (s n) c -> (b s) n c', s = num_sharded_batches)

    logits = logits.split(sizes.tolist(), dim = 0)

    logits, _ = split_by_rank(logits)

    return logits

# main class

class RingAttention(Module):
    @beartype
    def __init__(
        self,
        dim: int,
        *,
        dim_head: int = 64,
        heads: int = 8,
        num_grouped_query_heads: int = 1,
        causal: bool = False,
        eps: float = 1e-10,
        bucket_size: int = 512,
        ring_attn: bool = False,
        ring_seq_size: int = 512,
        max_lookback_seq_len: int | None = None,
        striped_ring_attn: bool = False,
        auto_shard_seq: bool = False,
        prenorm: bool = True,
        force_regular_attn: bool = False,
        rotary_embed: bool = False,
        rotary_embed_theta: int = 10000,
        use_cuda_kernel: bool | None = None
    ):
        super().__init__()
        # whether to use flash attention cuda kernel

        use_cuda_kernel = default(use_cuda_kernel, torch.cuda.is_available())
        assert not (use_cuda_kernel and not torch.cuda.is_available())
        self.use_cuda_kernel = use_cuda_kernel

        self.eps = eps
        self.heads = heads
        self.dim_head = dim_head

        assert divisible_by(heads, num_grouped_query_heads), f'number of query heads ({heads}) must be divisible by the groups ({num_grouped_query_heads})'

        kv_heads = heads // num_grouped_query_heads
        self.num_grouped_query_heads = num_grouped_query_heads
        self.qkv_head_breakdown = (heads, kv_heads, kv_heads)

        self.scale = dim_head ** -0.5
        self.causal = causal

        assert (not ring_attn) or divisible_by(ring_seq_size, bucket_size), f'ring seq size {ring_seq_size} is not divisible by bucket size {bucket_size}'

        self.ring_attn = ring_attn
        self.max_lookback_seq_len = max_lookback_seq_len
        self.striped_ring_attn = striped_ring_attn

        self.using_striped_ring_cuda = striped_ring_attn and use_cuda_kernel

        self.force_regular_attn = force_regular_attn
        self.auto_shard_seq = default(auto_shard_seq, ring_attn) # this should be done at the transformer level on the token ids for efficiency, but for testing purposes

        assert not (not self.ring_attn and self.auto_shard_seq)

        self.ring_seq_size = ring_seq_size
        self.bucket_size = bucket_size

        # rotary

        self.rotary_embed = None
        if rotary_embed:
            self.rotary_embed = RingRotaryEmbedding(
                dim = dim_head,
                ring = ring_attn,
                striped = striped_ring_attn,
                theta = rotary_embed_theta,
                buckets = ring_seq_size // bucket_size
            )

        # projections

        dim_inner = dim_head * heads
        dim_kv_inner = dim_head * kv_heads

        self.to_qkv_split = (dim_inner, dim_kv_inner, dim_kv_inner)

        self.to_qkv = nn.Sequential(
            RMSNorm(dim) if prenorm else nn.Identity(),
            nn.Linear(dim, dim_inner + (dim_kv_inner * 2), bias = False)
        )

        self.to_out = nn.Linear(dim_inner, dim, bias = False)

    def forward(
        self,
        x,
        mask = None,
        rotary_emb = None,
        ring_size = None,
    ):
        """
        einstein notation

        b - batch
        h - heads
        d - feature dimension
        n, i, j - sequence
        """

        ring_size = default(ring_size, get_world_size())
        ring_attn = self.ring_attn & is_distributed()
        auto_shard_seq = self.auto_shard_seq & is_distributed()

        using_striped_ring_cuda = x.is_cuda and self.using_striped_ring_cuda
        striped_bucket_size = self.bucket_size if not using_striped_ring_cuda else self.ring_seq_size

        seq_len = x.shape[1]

        if auto_shard_seq:
            x, mask = maybe_pad_seq_and_mask(x, mask, self.ring_seq_size)

            if self.striped_ring_attn:
                x = rearrange(x, 'b (i j) d -> b (j i) d', i = striped_bucket_size)

                if exists(mask):
                    mask = rearrange(mask, 'b (i j) -> b (j i)', i = striped_bucket_size)

            (x, mask), batch_sizes, num_sharded_batches = sharded_batch_to_sharded_seq(x, mask, self.ring_seq_size)

        device = x.device

        qkv = self.to_qkv(x)

        q, k, v = rearrange(qkv, 'b n (h d) -> b n h d', d = self.dim_head).split(self.qkv_head_breakdown, dim = -2)

        # rotary relative positions

        if not exists(rotary_emb) and exists(self.rotary_embed):
            rotary_emb = self.rotary_embed(q.shape[-3])

        if exists(rotary_emb):
            q = apply_rotary_pos_emb(rotary_emb, q)
            k = apply_rotary_pos_emb(rotary_emb, k)

        # regular attention vs flash w/ or w/o kv ring reduce

        out = default_attention(q, k, v, mask = mask, causal = self.causal)


        # combine heads

        out = rearrange(out, 'b n h d -> b n (h d)')
        out = self.to_out(out)

        if auto_shard_seq:
            out = sharded_seq_to_sharded_batch(out, batch_sizes, num_sharded_batches)

            if self.striped_ring_attn:
                out = rearrange(out, 'b (j i) d -> b (i j) d', i = striped_bucket_size)

            out = out[:, :seq_len]

        return out

# simple transformer for end2end testing

class RMSNorm(Module):
    def __init__(self, dim):
        super().__init__()
        self.scale = dim ** 0.5
        self.gamma = nn.Parameter(torch.ones(dim))

    def forward(self, x):
        return F.normalize(x, dim = -1) * self.scale * self.gamma
