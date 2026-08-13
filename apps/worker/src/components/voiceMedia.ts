export function audioTracks(stream: MediaStream): MediaStreamTrack[] {
  const getAudioTracks = (stream as MediaStream & {
    getAudioTracks?: () => MediaStreamTrack[];
  }).getAudioTracks;
  return typeof getAudioTracks === "function" ? getAudioTracks.call(stream) : stream.getTracks();
}

export function createVoicePlaybackAnalyser(context: AudioContext): AnalyserNode {
  const analyser = context.createAnalyser();
  analyser.fftSize = 1024;
  analyser.smoothingTimeConstant = 0.5;
  analyser.connect(context.destination);
  return analyser;
}

export function resamplePcm16(
  input: Float32Array,
  inputRate: number,
  outputRate: number,
): ArrayBuffer {
  const ratio = inputRate / outputRate;
  const length = Math.max(1, Math.floor(input.length / ratio));
  const output = new Int16Array(length);
  for (let index = 0; index < length; index += 1) {
    const from = Math.floor(index * ratio);
    const to = Math.min(input.length, Math.floor((index + 1) * ratio));
    let sum = 0;
    for (let cursor = from; cursor < to; cursor += 1) sum += input[cursor] ?? 0;
    const sample = Math.max(-1, Math.min(1, sum / Math.max(1, to - from)));
    output[index] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  return output.buffer;
}

export function safeDisconnect(node: AudioNode): void {
  try {
    node.disconnect();
  } catch {
    // Disconnect is best-effort for nodes whose setup never completed.
  }
}
