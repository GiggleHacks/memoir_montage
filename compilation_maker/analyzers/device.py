"""GPU device detection for ONNX Runtime and PyTorch."""
from __future__ import annotations

import threading

_onnx_providers: list[str] | None = None
_torch_device: str | None = None
_lock = threading.Lock()


def get_onnx_providers(prefer_gpu: bool = True) -> list[str]:
    global _onnx_providers
    if _onnx_providers is not None:
        return _onnx_providers
    with _lock:
        if _onnx_providers is not None:
            return _onnx_providers
        providers = ["CPUExecutionProvider"]
        if prefer_gpu:
            try:
                import onnxruntime
                available = onnxruntime.get_available_providers()
                if "CUDAExecutionProvider" in available:
                    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
            except Exception:
                pass
        _onnx_providers = providers
    return _onnx_providers


def get_torch_device(prefer_gpu: bool = True) -> str:
    global _torch_device
    if _torch_device is not None:
        return _torch_device
    with _lock:
        if _torch_device is not None:
            return _torch_device
        device = "cpu"
        if prefer_gpu:
            try:
                import torch
                if torch.cuda.is_available():
                    device = "cuda"
            except Exception:
                pass
        _torch_device = device
    return _torch_device
