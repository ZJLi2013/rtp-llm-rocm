from typing import Any, Dict, List, Set, Union, Optional, NamedTuple
from pathlib import PosixPath, Path
import json
import enum
import os
import logging
import torch
import struct
from safetensors import safe_open

from maga_transformer.utils.time_util import Timer
import maga_transformer.utils.meta_pickler as meta_pickler

class CkptType(enum.Enum):
    torch = "torch"
    safetensors = "safetensors"

class FinetuneType(enum.Enum):
    pretrain = "pretrain"
    lora = "lora"
    ptuning = "ptuning"

class TrainType(enum.Enum):
    deepspeed = "deepspeed"
    megatron = "megatron"

class CkptFileInfo:

    """The abstract file for any type checkpoint file.

    """

    file_name: str
    metadata: Dict[str, Any]

    tp_size: int
    tp_rank: int
    pp_size: int
    pp_rank: int

    ckpt_type: CkptType
    finetune_type: FinetuneType
    train_type: TrainType
    

    def __init__(self, file_name: str, finetune_type: FinetuneType = FinetuneType.pretrain, 
                 train_type: TrainType = TrainType.deepspeed,
                 tp_size: int = 1, tp_rank: int = 1, pp_size: int = 1, pp_rank: int = 1) -> None:

        if file_name.endswith(('.safetensors')):
            self.ckpt_type = CkptType.safetensors
        elif file_name.endswith(('.pth', '.bin', '.pt')):
            self.ckpt_type = CkptType.torch
        else:
            raise Exception(f"unsupport file type : {file_name}")

        self.file_name = file_name
        self.finetune_type = finetune_type
        self.train_type = train_type
        self.tp_size = tp_size
        self.tp_rank = tp_rank
        self.pp_size = pp_size
        self.pp_rank = pp_rank
        self._load_meta(self.file_name)
    
    def get_tensor_names(self) -> List[str]:
        return [name for name in self.metadata.keys()]

    @property
    def tensor_num(self) -> int:
        return len(self.metadata.keys())

    @property
    def pretrain_pp_tp(self):
        if self.finetune_type == FinetuneType.pretrain:
            return (self.pp_size, self.tp_size)
        return (1,1)
    
    def is_safetensor(self) -> bool:
        if self.ckpt_type == CkptType.safetensors:
            return True
        return False

    def get_metadata(self) -> Dict[str, Any]:
        return self.metadata

    def _load_meta(self, file: str) -> Dict[str, Any]:
        # https://huggingface.co/docs/safetensors/metadata_parsing
        if self.is_safetensor():
            meta = {}
            with safe_open(file, framework="pt") as f_:
                with open(file, 'rb') as f:
                    length_of_header = struct.unpack('<Q', f.read(8))[0]
                    header = f.read(length_of_header)
                    metadata = json.loads(header)
                for key in f_.keys():
                    meta[key] = metadata[key]['data_offsets'][0]
            self.metadata = meta
        else:
            self.metadata = torch.load(file, pickle_module=meta_pickler)

    def load_tensor(self, name: str, datatype: str = torch.float16) -> torch.Tensor:
        path: str = self.file_name
        if self.is_safetensor():
            with safe_open(path, framework="pt") as f:
                return f.get_tensor(name).to(datatype)
        else:
            meta = self.metadata[name]
            def __preload_tensor_content(file, tensor, meta, storage_offset):
                tensor_offset = meta[1] * torch._utils._element_size(dtype)
                tensor_bytes = tensor.numel() * torch._utils._element_size(dtype)
                with Timer() as t:
                    with open(file, 'rb') as f:
                        f.seek(storage_offset + tensor_offset)
                        f.read(tensor_bytes)
            with open(path, 'rb') as f:
                size = os.path.getsize(path)
                if isinstance(path, PosixPath):
                    path = path.as_posix()
                overall_storage = torch.UntypedStorage.from_file(path, False, size)
                with torch.serialization._open_zipfile_reader(f) as zip_file_reader:
                    storage_args = meta[0]
                    dtype = storage_args[1].dtype
                    name = 'data/' + storage_args[2]
                    n_elements = storage_args[4]
                    n_bytes = n_elements * torch._utils._element_size(dtype)
                    storage_offset = zip_file_reader.get_record_offset(name)
                    storage = overall_storage[storage_offset:storage_offset + n_bytes]
                    typed_storage = torch.storage.TypedStorage(
                        wrap_storage=storage,
                        dtype=dtype,
                        _internal=True)
                    tensor = torch._utils._rebuild_tensor_v2(typed_storage, *meta[1:])
                    # preread tensor content to memory: avoid multi-thread read file (e.g. from Fuse) cause cache miss
                    __preload_tensor_content(path, tensor, meta, storage_offset)
                    tensor = tensor.contiguous().to(datatype)

                    return tensor

    def __lt__(self, other):
        if not isinstance(other, CkptFileInfo):
            raise NotImplemented(f"other's type : {type(other)} is not CkptFileInfo")
        if self.pp_size < other.pp_size:
            return True
        if self.tp_size < other.tp_size:
            return True
        if self.finetune_type == FinetuneType.PRETRAIN and other.finetune_type != FinetuneType.PRETRAIN:
            return True
        if self.finetune_type != FinetuneType.PRETRAIN and other.finetune_type == FinetuneType.PRETRAIN:
            return False
        # 暂时不支持LoRA 和 PTuning 共存
        assert(self.finetune_type == other.finetune_type)
        return self.file_name < other.file_name