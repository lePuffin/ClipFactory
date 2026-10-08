"""Pure FFmpeg argument construction from a validated CompositionSpec."""

from __future__ import annotations

from pathlib import Path

from clipfactory.composition.spec import CompositionSpec, VisualInput


def build_ffmpeg_command(spec: CompositionSpec) -> list[str]:
    _validate_spec(spec)
    arguments = ["-hide_banner", "-nostdin", "-y", "-filter_complex_threads", "1"]
    for index, segment in enumerate(spec.segments):
        if segment.media_type == "image":
            arguments.extend(
                [
                    "-loop",
                    "1",
                    "-framerate",
                    str(spec.fps),
                    "-t",
                    _seconds(_render_duration(spec, index)),
                    "-i",
                    str(segment.path),
                ]
            )
        else:
            arguments.extend(["-t", _seconds(_render_duration(spec, index)), "-i", str(segment.path)])
    narration_index = len(spec.segments)
    arguments.extend(["-i", str(spec.narration_path)])
    music_index = narration_index + 1
    if spec.music_path is not None:
        arguments.extend(["-stream_loop", "-1", "-i", str(spec.music_path)])
    overlay_offset = narration_index + 1 + int(spec.music_path is not None)
    for overlay in spec.overlays:
        arguments.extend(["-loop", "1", "-framerate", str(spec.fps), "-i", str(overlay.path)])
    sound_offset = overlay_offset + len(spec.overlays)
    for cue in spec.sound_effects:
        arguments.extend(["-i", str(cue.path)])
    filters = [_visual_filter(index, segment, spec) for index, segment in enumerate(spec.segments)]
    video_label = _transition_filter(spec, filters)
    for index, overlay in enumerate(spec.overlays):
        duration = overlay.end_seconds - overlay.start_seconds
        fade = min(overlay.fade_seconds, duration / 2)
        cue_label = f"overlaycue{index}"
        output_label = f"editorial{index}"
        filters.append(
            f"[{overlay_offset + index}:v]format=rgba,trim=duration={_seconds(duration)},"
            f"setpts=PTS-STARTPTS,fade=t=in:st=0:d={_seconds(fade)}:alpha=1,"
            f"fade=t=out:st={_seconds(duration - fade)}:d={_seconds(fade)}:alpha=1,"
            f"setpts=PTS+{_seconds(overlay.start_seconds)}/TB[{cue_label}]"
        )
        filters.append(
            f"[{video_label}][{cue_label}]overlay=x={overlay.x}:y={overlay.y}:eof_action=pass:"
            f"enable='between(t,{_seconds(overlay.start_seconds)},{_seconds(overlay.end_seconds)})'[{output_label}]"
        )
        video_label = output_label
    font_options = f":fontsdir='{_escape_filter_path(spec.fonts_dir)}'" if spec.fonts_dir else ""
    video_filter = "".join(
        [
            "[",
            f"{video_label}",
            "]scale=out_range=tv,format=yuv420p,setparams=range=limited,s",
            "ubtitles=filename='",
            f"{_escape_filter_path(spec.caption_file)}",
            "'",
            f"{font_options}",
            "[vout]",
        ]
    )
    filters.append(video_filter)
    audio_filter = _audio_filter(spec, narration_index, music_index, sound_offset)
    filters.append(audio_filter)
    arguments.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-t",
            _seconds(spec.duration_seconds),
            "-r",
            str(spec.fps),
            "-c:v",
            spec.video_codec,
            "-crf",
            str(spec.crf),
            "-preset",
            spec.preset,
            "-pix_fmt",
            spec.pixel_format,
            "-color_range",
            "tv",
            "-c:a",
            spec.audio_codec,
            "-b:a",
            spec.audio_bitrate,
            "-ar",
            str(spec.audio_sample_rate),
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            str(spec.output_path),
        ]
    )
    return arguments


def _validate_spec(spec: CompositionSpec) -> None:
    if not spec.segments:
        raise ValueError("composition requires at least one visual segment")
    if spec.width <= 0 or spec.height <= 0 or spec.width * 16 != spec.height * 9:
        raise ValueError("composition output must use a positive 9:16 frame")
    if spec.fps < 24 or spec.fps > 60:
        raise ValueError("composition frame rate must be between 24 and 60")
    if spec.narration_duration_seconds <= 0 or spec.lead_in_seconds < 0 or spec.tail_seconds < 0:
        raise ValueError("composition durations are invalid")
    if any(segment.duration_seconds <= 0 or segment.width <= 0 or segment.height <= 0 for segment in spec.segments):
        raise ValueError("visual segment dimensions and durations must be positive")
    if abs(sum(segment.duration_seconds for segment in spec.segments) - spec.duration_seconds) > 1 / spec.fps:
        raise ValueError("visual segments must cover Clip duration within one frame")
    for overlay in spec.overlays:
        if not 0 <= overlay.start_seconds < overlay.end_seconds <= spec.duration_seconds:
            raise ValueError("editorial overlay must lie inside the Clip timeline")
        if overlay.fade_seconds < 0 or min(overlay.width, overlay.height) <= 0:
            raise ValueError("editorial overlay dimensions and fade must be valid")
        if (
            overlay.x < 0
            or overlay.y < 0
            or overlay.x + overlay.width > spec.width
            or overlay.y + overlay.height > spec.height
        ):
            raise ValueError("editorial overlay exceeds output bounds")
    for index, overlay in enumerate(spec.overlays):
        for other in spec.overlays[index + 1 :]:
            overlap_time = overlay.start_seconds < other.end_seconds and other.start_seconds < overlay.end_seconds
            overlap_space = (
                overlay.x < other.x + other.width
                and other.x < overlay.x + overlay.width
                and overlay.y < other.y + other.height
                and other.y < overlay.y + overlay.height
            )
            if overlap_time and overlap_space:
                raise ValueError("editorial overlays collide")
    for cue in spec.sound_effects:
        if not 0 <= cue.start_seconds < cue.start_seconds + cue.duration_seconds <= spec.duration_seconds:
            raise ValueError("sound cue must lie inside the Clip timeline")
        if cue.fade_seconds < 0 or not -60 <= cue.gain_db <= 0:
            raise ValueError("sound cue gain or fade is invalid")


def _visual_filter(index: int, segment: VisualInput, spec: CompositionSpec) -> str:
    source = f"[{index}:v]"
    scale = "".join(
        [
            "scale=",
            f"{spec.width}",
            ":",
            f"{spec.height}",
            ":force_original_aspect_ratio=increase,crop=",
            f"{spec.width}",
            ":",
            f"{spec.height}",
        ]
    )
    if segment.width / segment.height >= 1.0:
        fit_filter = "".join(
            [
                "split[bg",
                f"{index}",
                "][fg",
                f"{index}",
                "];[bg",
                f"{index}",
                "]",
                f"{scale}",
                ",boxblur=24:2,eq=brightness=-0.20[blur",
                f"{index}",
                "];[fg",
                f"{index}",
                "]scale=",
                f"{spec.width}",
                ":",
                f"{spec.height}",
                ":force_original_aspect_ratio=decrease[fit",
                f"{index}",
                "];[blur",
                f"{index}",
                "][fit",
                f"{index}",
                "]overlay=(W-w)/2:(H-h)/2",
            ]
        )
    else:
        fit_filter = scale
    duration = _render_duration(spec, index)
    motion = _motion_filter(segment.motion, spec, duration)
    hold = "tpad=stop_mode=clone:stop_duration=1," if segment.media_type == "video" else ""
    label = (
        "".join(
            [
                ",drawtext=text='",
                f"{segment.source_label}",
                "':fontsize=18:fontcolor=white:box=1:boxcolor=black@0.65:boxb",
                "orderw=8:x=24:y=32",
            ]
        )
        if segment.source_label
        else ""
    )
    return "".join(
        [
            f"{source}",
            f"{fit_filter}",
            ",fps=",
            f"{spec.fps}",
            ",",
            f"{motion}",
            "fps=",
            f"{spec.fps}",
            ",format=yuv420p,setsar=1,",
            f"{hold}",
            "trim=duration=",
            f"{_seconds(duration)}",
            ",settb=AVTB,setpts=PTS-STARTPTS",
            f"{label}",
            "[v",
            f"{index}",
            "]",
        ]
    )


def _render_duration(spec: CompositionSpec, index: int) -> float:
    outgoing = index + 1 < len(spec.segments) and spec.segments[index + 1].transition_in != "cut"
    return spec.segments[index].duration_seconds + (spec.transition_seconds if outgoing else 0)


def _transition_filter(spec: CompositionSpec, filters: list[str]) -> str:
    if len(spec.segments) == 1:
        return "v0"
    if all(segment.transition_in == "cut" for segment in spec.segments[1:]):
        inputs = "".join(f"[v{index}]" for index in range(len(spec.segments)))
        filters.append(f"{inputs}concat=n={len(spec.segments)}:v=1:a=0[vconcat]")
        return "vconcat"
    current = "v0"
    current_duration = _render_duration(spec, 0)
    transition_names = {
        "cut": "fade",
        "crossfade": "fade",
        "fade_black": "fadeblack",
        "slide_left": "slideleft",
        "slide_up": "slideup",
    }
    for index, segment in enumerate(spec.segments[1:], start=1):
        if segment.transition_in == "cut":
            output = f"vc{index}"
            filters.append(f"[{current}][v{index}]concat=n=2:v=1:a=0[{output}]")
            current_duration += _render_duration(spec, index)
            current = output
            continue
        duration = spec.transition_seconds
        offset = max(0.0, current_duration - duration)
        output = f"vx{index}"
        filters.append(
            "".join(
                [
                    "[",
                    f"{current}",
                    "][v",
                    f"{index}",
                    "]xfade=transition=",
                    f"{transition_names[segment.transition_in]}",
                    ":duration=",
                    f"{_seconds(duration)}",
                    ":offset=",
                    f"{_seconds(offset)}",
                    "[",
                    f"{output}",
                    "]",
                ]
            )
        )
        current_duration += _render_duration(spec, index) - duration
        current = output
    return current


def _motion_filter(motion: str, spec: CompositionSpec, duration_seconds: float) -> str:
    maximum = {"low": 1.05, "medium": 1.1, "high": 1.2}[spec.motion_intensity]
    frames = max(1, round(duration_seconds * spec.fps) - 1)
    step = (maximum - 1) / frames
    zoom = {
        "zoom_in": "".join(
            ["zoompan=z='min(1+on*", f"{step:.8f}", ",", f"{maximum:.2f}", ")':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2'"]
        ),
        "zoom_out": "".join(
            ["zoompan=z='max(", f"{maximum:.2f}", "-on*", f"{step:.8f}", ",1)':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2'"]
        ),
        "ken_burns": "".join(
            ["zoompan=z='min(1+on*", f"{step:.8f}", ",", f"{maximum:.2f}", ")':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2'"]
        ),
    }.get(motion)
    if motion.startswith("pan_"):
        horizontal = motion in {"pan_left", "pan_right"}
        fraction = f"1-on/{frames}" if motion in {"pan_left", "pan_up"} else f"on/{frames}"
        position = f"(iw-iw/zoom)*({fraction})" if horizontal else f"(ih-ih/zoom)*({fraction})"
        zoom = "".join(
            [
                "zoompan=z='",
                f"{maximum:.2f}",
                "':x='",
                f"{(position if horizontal else 'iw/2-iw/zoom/2')}",
                "':y='",
                f"{(position if not horizontal else 'ih/2-ih/zoom/2')}",
                "'",
            ]
        )
    if zoom is None:
        return ""
    return f"scale=w=4*iw:h=4*ih:flags=lanczos,format=yuv444p,{zoom}:d=1:s={spec.width}x{spec.height}:fps={spec.fps},"


def _audio_filter(spec: CompositionSpec, narration_index: int, music_index: int, sound_offset: int) -> str:
    delay_ms = round(spec.lead_in_seconds * 1000)
    narration = "".join(
        [
            "[",
            f"{narration_index}",
            ":a]adelay=",
            f"{delay_ms}",
            ":all=1,apad=whole_dur=",
            f"{_seconds(spec.duration_seconds)}",
            ",atrim=duration=",
            f"{_seconds(spec.duration_seconds)}",
            ",loudnorm=I=",
            f"{spec.narration_loudness_lufs}",
            ":TP=-1.5[narration]",
        ]
    )
    if spec.music_path is None and not spec.sound_effects:
        return narration.removesuffix("[narration]") + "[aout]"
    speaking = _speaking_expression(spec)
    ducked = 10 ** (spec.music_ducked_level_db / 20)
    unducked = 10 ** (spec.music_unducked_level_db / 20)
    music = "".join(
        [
            "[",
            f"{music_index}",
            ":a]atrim=duration=",
            f"{_seconds(spec.duration_seconds)}",
            ",volume='",
            f"{_seconds(ducked)}",
            "*(",
            f"{speaking}",
            ")+",
            f"{_seconds(unducked)}",
            "*(1-(",
            f"{speaking}",
            "))':eval=frame,afade=t=in:st=0:d=1,afade=t=out:st=",
            f"{_seconds(max(0, spec.duration_seconds - 2))}",
            ":d=2[music]",
        ]
    )
    filters = [narration]
    labels = ["[narration]"]
    if spec.music_path is not None:
        filters.append(music)
        labels.append("[music]")
    for index, cue in enumerate(spec.sound_effects):
        fade = min(cue.fade_seconds, cue.duration_seconds / 2)
        filters.append(
            f"[{sound_offset + index}:a]atrim=duration={_seconds(cue.duration_seconds)},asetpts=PTS-STARTPTS,"
            f"loudnorm=I={spec.narration_loudness_lufs}:TP=-2,volume={_seconds(10 ** (cue.gain_db / 20))},"
            f"afade=t=in:st=0:d={_seconds(fade)},"
            f"afade=t=out:st={_seconds(cue.duration_seconds - fade)}:d={_seconds(fade)},"
            f"adelay={round(cue.start_seconds * 1000)}:all=1[sfx{index}]"
        )
        labels.append(f"[sfx{index}]")
    filters.append(
        f"{''.join(labels)}amix=inputs={len(labels)}:duration=first:normalize=0,"
        f"loudnorm=I={spec.narration_loudness_lufs}:TP=-2[aout]"
    )
    return ";".join(filters)


def _speaking_expression(spec: CompositionSpec) -> str:
    spans: list[tuple[float, float]] = []
    for start, end in spec.narration_word_spans:
        shifted = (start + spec.lead_in_seconds, end + spec.lead_in_seconds)
        if spans and shifted[0] - spans[-1][1] <= 0.8:
            spans[-1] = (spans[-1][0], shifted[1])
        else:
            spans.append(shifted)
    if not spans:
        return "0"
    return "+".join((f"between(t,{_seconds(start)},{_seconds(end)})" for start, end in spans))


def _escape_filter_path(path: Path) -> str:
    value = str(path.resolve())
    return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _seconds(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")
