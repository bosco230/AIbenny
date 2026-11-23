import subprocess, json, os

python = r"C:\AI-Girlfriend\cantonese-tts\.venv\Scripts\python.exe"
worker = r"C:\AI-Girlfriend\openmimicry-main\openmimicry-main\packages\openmimicry-voice\src\openmimicry\voice\workers\qwen3_job.py"
output = r"C:\AI-Girlfriend\cantonese-tts\worker_test.wav"

p = subprocess.Popen(
    [python, worker, "--server"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=None,
    text=True,
    encoding="utf-8",
)

ready = p.stdout.readline()
print("Worker:", ready.strip())

p.stdin.write(json.dumps({
    "type": "synthesize",
    "text": "喂，你食咗飯未呀？今日天氣幾好，我哋出去行下街啦。",
    "output": output
}, ensure_ascii=False) + "\n")
p.stdin.flush()

result = p.stdout.readline()
print("Result:", result.strip())

p.stdin.write(json.dumps({"type": "shutdown"}) + "\n")
p.stdin.flush()
p.wait(timeout=30)

print("WAV exists:", os.path.exists(output))
if os.path.exists(output):
    print("WAV size:", os.path.getsize(output), "bytes")

