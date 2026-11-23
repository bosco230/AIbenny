import sys
import json
import traceback
import argparse
import time
from contextlib import redirect_stdout
# Force UTF-8 for Chinese text received from stdin.
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

MODEL_PATH = r"C:\AI-Girlfriend\cantonese-tts\hk-cantonese"
SPEAKER = "hk_voice_343"

def send(data):
    sys.stdout.write(json.dumps(data, ensure_ascii=False) + "\n")
    sys.stdout.flush()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", action="store_true")
    args = parser.parse_args()

    try:
        # Keep stdout reserved for JSON protocol messages.
        with redirect_stdout(sys.stderr):
            import torch
            import soundfile as sf
            from qwen_tts import Qwen3TTSModel

            print("Loading Cantonese Qwen3 TTS model...", file=sys.stderr)
            model = Qwen3TTSModel.from_pretrained(
                MODEL_PATH,
                device_map="cuda:0",
                dtype=torch.bfloat16,
                attn_implementation="sdpa",
            )

        send({"type": "ready"})

        if not args.server:
            return

        for line in sys.stdin:
            try:
                request = json.loads(line)
                if request.get("type") == "shutdown":
                    send({"type": "complete"})
                    break

                if request.get("type") != "synthesize":
                    send({"type": "error", "message": "Unknown request type"})
                    continue

                text = request.get("text", "")
                print("WORKER RECEIVED TEXT:", repr(text), file=sys.stderr)
                output_path = request.get("output", "")

                if not text.strip():
                    send({"type": "error", "message": "Text is empty"})
                    continue

                from unittest.mock import patch

                original_generate = model.model.generate
                original_decode = model.model.speech_tokenizer.decode

                def timed_generate(*args, **kwargs):
                    started = time.perf_counter()
                    result = original_generate(*args, **kwargs)
                    torch.cuda.synchronize()
                    print(
                        f"QWEN3 GENERATE: {time.perf_counter() - started:.3f}s",
                        file=sys.stderr,
                    )
                    return result

                def timed_decode(*args, **kwargs):
                    started = time.perf_counter()
                    result = original_decode(*args, **kwargs)
                    torch.cuda.synchronize()
                    print(
                        f"QWEN3 DECODE: {time.perf_counter() - started:.3f}s",
                        file=sys.stderr,
                    )
                    return result

                predictor = model.model.talker.code_predictor
                original_predictor_generate = predictor.generate
                predictor_stats = {"calls": 0, "seconds": 0.0}

                def timed_predictor_generate(*args, **kwargs):
                    torch.cuda.synchronize()
                    started = time.perf_counter()
                    result = original_predictor_generate(*args, **kwargs)
                    torch.cuda.synchronize()
                    predictor_stats["calls"] += 1
                    predictor_stats["seconds"] += time.perf_counter() - started
                    return result
                original_forward = predictor.forward
                forward_stats = {"calls": 0, "seconds": 0.0}

                def timed_forward(*args, **kwargs):
                    torch.cuda.synchronize()
                    started = time.perf_counter()
                    result = original_forward(*args, **kwargs)
                    torch.cuda.synchronize()
                    forward_stats["calls"] += 1
                    forward_stats["seconds"] += time.perf_counter() - started
                    return result

                synthesis_started = time.perf_counter()
                with patch.object(predictor, "forward", timed_forward), patch.object(predictor, "generate", timed_predictor_generate), patch.object(model.model, "generate", timed_generate), patch.object(
                    model.model.speech_tokenizer, "decode", timed_decode
                ):
                    wavs, sr = model.generate_custom_voice(
                        text=text,
                        language="Chinese",
                        speaker=SPEAKER,
                    )
                print(f"QWEN3 CODE PREDICTOR: calls={predictor_stats['calls']} duration={predictor_stats['seconds']:.3f}s", file=sys.stderr)
                print(f"QWEN3 FORWARD: calls={forward_stats['calls']} duration={forward_stats['seconds']:.3f}s", file=sys.stderr)
                print(f"QWEN3 OTHER: duration={predictor_stats['seconds'] - forward_stats['seconds']:.3f}s", file=sys.stderr)
                synthesis_elapsed = time.perf_counter() - synthesis_started
                print(
                    f"QWEN3 SYNTHESIS: {synthesis_elapsed:.3f}s",
                    file=sys.stderr,
                )

                write_started = time.perf_counter()
                sf.write(output_path, wavs[0], sr)
                write_elapsed = time.perf_counter() - write_started
                print(
                    f"QWEN3 WAV WRITE: {write_elapsed:.3f}s",
                    file=sys.stderr,
                )

                send({
                    "type": "complete",
                    "output": output_path,
                    "sample_rate": sr,
                })

            except Exception as exc:
                traceback.print_exc(file=sys.stderr)
                send({"type": "error", "message": str(exc)})

    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        send({"type": "error", "message": str(exc)})
        sys.exit(1)

if __name__ == "__main__":
    main()
