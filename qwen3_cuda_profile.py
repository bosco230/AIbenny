import time
import torch
from torch.profiler import profile, ProfilerActivity
from qwen_tts import Qwen3TTSModel

MODEL_PATH = r"C:\AI-Girlfriend\cantonese-tts\hk-cantonese"
SPEAKER = "hk_voice_343"
TEXT = "你好呀，今日過得點呀？"

print("Loading Qwen3 TTS model...", flush=True)

model = Qwen3TTSModel.from_pretrained(
    MODEL_PATH,
    device_map="cuda:0",
    dtype=torch.bfloat16,
    attn_implementation="sdpa",
)

print("Model loaded. Starting CUDA profiling...", flush=True)

torch.cuda.synchronize()

with profile(
    activities=[ProfilerActivity.CPU, ProfilerActivity.CUDA],
    record_shapes=False,
    profile_memory=False,
    with_stack=False,
) as prof:
    started = time.perf_counter()

    wavs, sr = model.generate_custom_voice(
        text=TEXT,
        language="Chinese",
        speaker=SPEAKER,
    )

    torch.cuda.synchronize()
    elapsed = time.perf_counter() - started

print(f"QWEN3 PROFILE SYNTHESIS: {elapsed:.3f}s")
print(f"Sample rate: {sr}")
print("CUDA KERNEL SUMMARY:")

events = prof.key_averages()

attention_events = [
    event for event in events
    if any(
        keyword in event.key.lower()
        for keyword in (
            "attention",
            "scaled_dot",
            "flash",
            "efficient",
            "cudnn",
        )
    )
]

if attention_events:
    for event in sorted(
        attention_events,
        key=lambda item: item.self_device_time_total,
        reverse=True,
    )[:20]:
        print(
            event.key,
            "calls=", event.count,
            "device_us=", event.self_device_time_total,
        )
else:
    print("No attention-related events found.")

print("PROFILE COMPLETE")

print()
print("TOP 20 GPU OPERATIONS:")
print(
    prof.key_averages().table(
        sort_by="self_device_time_total",
        row_limit=20,
    )
)
