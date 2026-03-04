import wave
import struct
import math

sample_rate = 16000
duration = 0.1  # 100 milliseconds
frequency = 880.0  # Hz (A5 - nice bright beep)
num_samples = int(sample_rate * duration)

with wave.open('/run/user/1000/gvfs/smb-share:server=grokbox.local,share=code/grokbox/beep.wav', 'w') as wav_file:
    wav_file.setnchannels(1)
    wav_file.setsampwidth(2)
    wav_file.setframerate(sample_rate)
    
    for i in range(num_samples):
        # 0.5 sec fade out to avoid clicks
        envelope = 1.0
        if i > num_samples - 400:
            envelope = (num_samples - i) / 400.0
        if i < 400:
            envelope = i / 400.0
            
        value = int(envelope * 16000 * math.sin(2 * math.pi * frequency * i / sample_rate))
        data = struct.pack('<h', value)
        wav_file.writeframesraw(data)
