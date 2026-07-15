import { useEffect, useRef, useState } from "react";
import type { VoiceState } from "../types";

/**
 * Hands-free voice loop, fully in-browser and offline:
 *   - captures the mic, runs a simple energy-based VAD to find utterance
 *     boundaries (speech start / trailing silence),
 *   - sends each captured utterance (webm) up via `onUtterance`,
 *   - plays the agent's spoken reply, then resumes listening.
 *
 * The mic is gated OFF whenever the server is transcribing/thinking/speaking or
 * while a reply is playing, so the agent never hears itself (no echo loop).
 */

const START_RMS = 0.02; // speech onset threshold
const SILENCE_MS = 900; // trailing silence that ends an utterance
const MIN_SPEECH_MS = 250; // ignore blips shorter than this
const MAX_UTTERANCE_MS = 14000;
const SEND_COOLDOWN_MS = 900; // bridge until the server flips to "transcribing"

export type MicPhase = "off" | "listening" | "capturing";

function pickMime(): string {
  const cands = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg"];
  const MR: any = (window as any).MediaRecorder;
  return cands.find((m) => MR?.isTypeSupported?.(m)) ?? "";
}

async function blobToB64(blob: Blob): Promise<string> {
  const buf = new Uint8Array(await blob.arrayBuffer());
  let bin = "";
  const chunk = 0x8000;
  for (let i = 0; i < buf.length; i += chunk) {
    bin += String.fromCharCode.apply(null, Array.from(buf.subarray(i, i + chunk)) as any);
  }
  return btoa(bin);
}

export function useVoice({
  enabled,
  serverState,
  audio,
  onUtterance,
  onError,
}: {
  enabled: boolean;
  serverState: VoiceState;
  audio: { b64: string; id: string } | null;
  onUtterance: (b64: string) => void;
  onError: (msg: string) => void;
}) {
  const [phase, setPhase] = useState<MicPhase>("off");
  const [level, setLevel] = useState(0);

  // Refs so the long-lived rAF loop always sees fresh values without re-running.
  const serverStateRef = useRef(serverState);
  serverStateRef.current = serverState;
  const phaseRef = useRef<MicPhase>("off");
  const playingRef = useRef(false);
  const cooldownUntil = useRef(0);
  const onUtteranceRef = useRef(onUtterance);
  onUtteranceRef.current = onUtterance;
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;

  const setPhaseBoth = (p: MicPhase) => {
    phaseRef.current = p;
    setPhase(p);
  };

  // --- mic + VAD lifecycle ---------------------------------------------------
  useEffect(() => {
    if (!enabled) {
      setPhaseBoth("off");
      return;
    }
    let stream: MediaStream | null = null;
    let ctx: AudioContext | null = null;
    let raf = 0;
    let recorder: MediaRecorder | null = null;
    let chunks: BlobPart[] = [];
    let recording = false;
    let speechDetected = false;
    let recStart = 0;
    let lastVoice = 0;
    let disposed = false;

    const stopRecorder = (send: boolean) => {
      if (recorder && recording) {
        const mime = recorder.mimeType;
        recorder.onstop = async () => {
          const blob = new Blob(chunks, { type: mime });
          chunks = [];
          if (send && speechDetected) {
            cooldownUntil.current = performance.now() + SEND_COOLDOWN_MS;
            try {
              onUtteranceRef.current(await blobToB64(blob));
            } catch (e) {
              onErrorRef.current((e as Error).message);
            }
          }
        };
        recording = false;
        try {
          recorder.stop();
        } catch {
          /* ignore */
        }
      }
    };

    const startRecorder = () => {
      chunks = [];
      speechDetected = false;
      recStart = performance.now();
      lastVoice = recStart;
      const mime = pickMime();
      recorder = new MediaRecorder(stream!, mime ? { mimeType: mime } : undefined);
      recorder.ondataavailable = (e) => e.data.size > 0 && chunks.push(e.data);
      recorder.start();
      recording = true;
    };

    (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        });
        if (disposed) return;
        ctx = new AudioContext();
        await ctx.resume();
        const src = ctx.createMediaStreamSource(stream);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 512;
        src.connect(analyser);
        const buf = new Float32Array(analyser.fftSize);

        const tick = () => {
          if (disposed) return;
          analyser.getFloatTimeDomainData(buf);
          let sum = 0;
          for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
          const rms = Math.sqrt(sum / buf.length);
          setLevel(rms);

          const now = performance.now();
          const eligible =
            serverStateRef.current === "idle" && !playingRef.current && now > cooldownUntil.current;

          if (eligible) {
            if (!recording) {
              startRecorder();
              setPhaseBoth("listening");
            } else {
              if (rms > START_RMS) {
                speechDetected = true;
                lastVoice = now;
                if (phaseRef.current !== "capturing") setPhaseBoth("capturing");
              }
              const silentFor = now - lastVoice;
              const hasSpeech = speechDetected && now - recStart > MIN_SPEECH_MS;
              if (hasSpeech && silentFor > SILENCE_MS) {
                stopRecorder(true);
                setPhaseBoth("listening");
              } else if (now - recStart > MAX_UTTERANCE_MS) {
                stopRecorder(speechDetected);
                setPhaseBoth("listening");
              } else if (!speechDetected && now - recStart > 6000) {
                stopRecorder(false); // recycle to avoid huge silent blobs
              }
            }
          } else if (recording) {
            stopRecorder(false);
          }
          raf = requestAnimationFrame(tick);
        };
        raf = requestAnimationFrame(tick);
        setPhaseBoth("listening");
      } catch {
        onErrorRef.current("Microphone access was denied or unavailable.");
        setPhaseBoth("off");
      }
    })();

    return () => {
      disposed = true;
      cancelAnimationFrame(raf);
      try {
        stopRecorder(false);
      } catch {
        /* ignore */
      }
      stream?.getTracks().forEach((t) => t.stop());
      ctx?.close();
      setPhaseBoth("off");
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  // --- play the agent's spoken reply (single instance, no overlap) ----------
  const audioElRef = useRef<HTMLAudioElement | null>(null);
  const lastPlayedId = useRef<string | null>(null);

  useEffect(() => {
    // Voice off or reply cleared → stop any playback.
    if (!enabled || !audio) {
      if (audioElRef.current) {
        audioElRef.current.pause();
        audioElRef.current.src = "";
        audioElRef.current = null;
      }
      playingRef.current = false;
      return;
    }
    if (audio.id === lastPlayedId.current) return; // dedupe replays
    lastPlayedId.current = audio.id;

    // Stop any currently-playing reply so two never overlap ("multiple voices").
    if (audioElRef.current) {
      audioElRef.current.pause();
      audioElRef.current.src = "";
      audioElRef.current = null;
    }

    const el = new Audio(`data:audio/wav;base64,${audio.b64}`);
    audioElRef.current = el;
    playingRef.current = true;
    const done = () => {
      if (audioElRef.current === el) {
        playingRef.current = false;
        // brief cooldown so the mic doesn't catch the tail/echo of the reply
        cooldownUntil.current = performance.now() + 1200;
      }
    };
    el.onended = done;
    el.onerror = done;
    el.play().catch(done);
    // Intentionally no cleanup-pause here: let the reply finish; a NEW reply
    // stops the previous one above.
  }, [audio, enabled]);

  return { phase, level };
}
