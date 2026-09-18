#!/usr/bin/env bash
# mix-encode.sh <work-dir> <voice-audio> <duration> <out.mp4> [music-file]
#
# Voice is compressed and normalised, clip audio and music duck under it via sidechain, SFX sit on top,
# and every stream is padded/trimmed to the exact duration before the final −14 LUFS pass.
set -euo pipefail

WORK="$1"
VOICE="$2"
DURATION="$3"
OUT="$4"
MUSIC="${5:-$WORK/music.wav}"
FPS=30

[[ -d "$WORK/frames" ]] || { echo "No frames in $WORK/frames"; echo "Next: run render-frames.sh"; exit 1; }
[[ -f "$WORK/sfx.wav" ]] || { echo "No sfx.wav in $WORK"; echo "Next: run synth_audio.py"; exit 1; }

# Clip audio from extract_clip.sh --audio: a speaking founder, a crowd, a product sound
shopt -s nullglob
CLIP_WAVS=("$WORK"/clips/*.wav)
shopt -u nullglob

INPUTS=(-i "$VOICE")
FILTER="[0:a]aresample=48000,apad=whole_dur=${DURATION},highpass=f=80,acompressor=threshold=-18dB:ratio=3:attack=5:release=120,loudnorm=I=-16:TP=-2,aresample=48000,asplit=3[voice][vkey][ckey];"
LAYERS="[voice]"
COUNT=1
NEXT=1

if (( ${#CLIP_WAVS[@]} > 0 )); then
  CLIP_LABELS=""
  for wav in "${CLIP_WAVS[@]}"; do
    INPUTS+=(-i "$wav")
    FILTER+="[${NEXT}:a]aresample=48000[c${NEXT}];"
    CLIP_LABELS+="[c${NEXT}]"
    NEXT=$(( NEXT + 1 ))
  done
  # Narration wins where they overlap; over a pause in the voice the clip plays at full level
  FILTER+="${CLIP_LABELS}amix=inputs=${#CLIP_WAVS[@]}:normalize=0:duration=longest,apad=whole_dur=${DURATION},asplit=2[craw][cclip];"
  FILTER+="[craw][ckey]sidechaincompress=threshold=0.03:ratio=6:attack=15:release=250[clips];"
  FILTER+="[vkey][cclip]amix=inputs=2:normalize=0:duration=first[key];"
  LAYERS+="[clips]"
  COUNT=$(( COUNT + 1 ))
else
  FILTER+="[ckey]anullsink;[vkey]anull[key];"
fi

if [[ -f "$MUSIC" ]]; then
  INPUTS+=(-i "$MUSIC")
  FILTER+="[${NEXT}:a]aresample=48000,volume=0.22[mus];[mus][key]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[duck];"
  LAYERS+="[duck]"
  COUNT=$(( COUNT + 1 ))
  NEXT=$(( NEXT + 1 ))
else
  FILTER+="[key]anullsink;"
fi

INPUTS+=(-i "$WORK/sfx.wav")
FILTER+="[${NEXT}:a]aresample=48000,volume=0.5[fx];"
LAYERS+="[fx]"
COUNT=$(( COUNT + 1 ))

ffmpeg -v error -y "${INPUTS[@]}" -filter_complex "\
${FILTER}\
${LAYERS}amix=inputs=${COUNT}:normalize=0:duration=longest,alimiter=limit=0.95,loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000,atrim=0:${DURATION}[out]" \
  -map "[out]" "$WORK/mix.wav"

# Grain defeats CRF on its own; the maxrate cap keeps a 108s vertical around 110 MB instead of 800+
ffmpeg -v error -y -framerate "$FPS" -i "$WORK/frames/f%05d.jpg" -i "$WORK/mix.wav" \
  -map 0:v -map 1:a -c:v libx264 -preset medium -crf 22 -maxrate 8M -bufsize 16M -pix_fmt yuv420p \
  -c:a aac -b:a 256k -t "$DURATION" -movflags +faststart "$OUT"

LOUDNESS=$(ffmpeg -hide_banner -i "$WORK/mix.wav" -af ebur128 -f null - 2>&1 | awk '/I:/{v=$2} END{print v}')
INFO=$(ffprobe -v error -show_entries stream=width,height:format=duration,size -of default=nw=1 "$OUT" | tr '\n' ' ')
echo "$(basename "$OUT") · ${LOUDNESS} LUFS · ${INFO}"
echo "Next: extract a frame from $(basename "$OUT") at a shot you changed and verify it"
