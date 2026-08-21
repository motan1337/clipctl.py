#!/usr/bin/env python3
"""
test_clipctl.py regression tests for clipctl if i fuck up shits (motan1337 in this case lol
or maybe u the one that is messing up with my code?)

Run with:  python3 -m unittest test_clipctl -v (linux)
           python -m unittest test_clipctl -v (windows)
No dependencies beyond the stdlib (and ffmpeg on path which clipctl
itself already requires at import time)
GREAT SUCCESS! VERY NICE!
"""

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

import clipctl

print("GREAT SUCCESS!")
print("VERY NICE!")
print("SPUNK FOR MILK VERY NICE!")

class TestParseTime(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(clipctl.parse_time("00:00:10"), 10)
        self.assertEqual(clipctl.parse_time("00:01:30"), 90)
        self.assertEqual(clipctl.parse_time("01:00:00"), 3600)

    def test_single_digit_hours(self):
        self.assertEqual(clipctl.parse_time("0:00:30"), 30)

    def test_long_hours(self):
        self.assertEqual(clipctl.parse_time("100:00:00"), 360000)
        self.assertEqual(clipctl.parse_time("1000:00:00"), 3600000)

    def test_rejects_invalid_minutes_seconds(self):
        self.assertIsNone(clipctl.parse_time("00:60:00"))
        self.assertIsNone(clipctl.parse_time("00:00:60"))

    def test_rejects_garbage(self):
        for bad in ("", "abc", "1:2:3", "00:00", "00-00-10", "00:00:10:00"):
            self.assertIsNone(clipctl.parse_time(bad), bad)

    def test_whitespace_tolerated(self):
        self.assertEqual(clipctl.parse_time("  00:00:05  "), 5)


class TestParseRange(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(clipctl.parse_range("00:00:10*00:01:30"), (10, 90))

    def test_end_must_exceed_start(self):
        self.assertIsNone(clipctl.parse_range("00:01:00*00:01:00"))
        self.assertIsNone(clipctl.parse_range("00:02:00*00:01:00"))

    def test_spaces_around_star(self):
        self.assertEqual(clipctl.parse_range("00:00:01 * 00:00:02"), (1, 2))

    def test_long_hours(self):
        self.assertEqual(clipctl.parse_range("100:00:00*100:00:10"),
                         (360000, 360010))

    def test_rejects_garbage(self):
        for bad in ("", "00:00:10", "00:00:10-00:00:20", "a*b"):
            self.assertIsNone(clipctl.parse_range(bad), bad)


class TestFmtTime(unittest.TestCase):
    def test_roundtrip(self):
        for secs in (0, 5, 59, 60, 3599, 3600, 86399, 360000):
            self.assertEqual(clipctl.parse_time(clipctl.fmt_time(secs)), secs)

    def test_rounds_floats(self):
        self.assertEqual(clipctl.fmt_time(1.4), "00:00:01")
        self.assertEqual(clipctl.fmt_time(1.6), "00:00:02")


class TestRemuxCompatible(unittest.TestCase):
    def _info(self, vcodec, acodec=None):
        return {"vcodec": vcodec, "acodec": acodec, "has_audio": acodec is not None}

    def test_h264_aac_into_mp4(self):
        self.assertTrue(clipctl.remux_compatible(self._info("h264", "aac"), ".mp4"))

    def test_the_ipcm_bug_stays_dead(self):
        self.assertFalse(clipctl.remux_compatible(self._info("h264", "pcm_s16le"), ".mp4"))

    def test_the_mp4v_bug_stays_dead(self):
        self.assertFalse(clipctl.remux_compatible(self._info("mpeg4", "mp3"), ".mp4"))

    def test_webm_only_takes_vp_family(self):
        self.assertTrue(clipctl.remux_compatible(self._info("vp9", "opus"), ".webm"))
        self.assertFalse(clipctl.remux_compatible(self._info("h264", "opus"), ".webm"))
        self.assertFalse(clipctl.remux_compatible(self._info("vp9", "aac"), ".webm"))

    def test_mkv_is_permissive(self):
        self.assertTrue(clipctl.remux_compatible(self._info("mpeg4", "mp3"), ".mkv"))
        self.assertTrue(clipctl.remux_compatible(self._info("h264", "flac"), ".mkv"))

    def test_video_only_source(self):
        self.assertTrue(clipctl.remux_compatible(self._info("h264"), ".mp4"))

    def test_unknown_target_rejects(self):
        self.assertFalse(clipctl.remux_compatible(self._info("h264", "aac"), ".xyz"))


class TestAudioCodecForExt(unittest.TestCase):
    def test_known_mappings(self):
        self.assertEqual(clipctl.audio_codec_for_ext(".mp3")[0], "libmp3lame")
        self.assertEqual(clipctl.audio_codec_for_ext(".wav"), ("pcm_s16le", None))
        self.assertEqual(clipctl.audio_codec_for_ext(".opus")[0], "libopus")

    def test_lossless_formats_have_no_bitrate(self):
        for ext in (".wav", ".flac"):
            self.assertIsNone(clipctl.audio_codec_for_ext(ext)[1], ext)

    def test_unknown_falls_back_to_mp3(self):
        self.assertEqual(clipctl.audio_codec_for_ext(".xyz")[0], "libmp3lame")


class TestBuildScaleFilter(unittest.TestCase):
    def test_no_resize_no_filter(self):
        self.assertIsNone(
            clipctl.build_scale_filter("libx264", 1920, 1080, 1920, 1080))

    def test_resize_scales_and_pads(self):
        vf = clipctl.build_scale_filter("libx264", 1280, 720, 1920, 1080)
        self.assertIn("scale=1920:1080", vf)
        self.assertIn("pad=1920:1080", vf)

    def test_vaapi_always_uploads(self):
        vf = clipctl.build_scale_filter("h264_vaapi", 1920, 1080, 1920, 1080)
        self.assertEqual(vf, "format=nv12,hwupload")
        vf = clipctl.build_scale_filter("h264_vaapi", 1280, 720, 1920, 1080)
        self.assertIn("scale=1920:1080", vf)
        self.assertIn("pad=1920:1080", vf)
        self.assertTrue(vf.endswith("hwupload"))

    def test_vaapi_pads_mixed_aspect_so_concat_parts_match(self):
        # the 4:3 into 16:9 case that used to produce a 1440x1080 part
        # next to 1920x1080 siblings malformed concat output
        vf = clipctl.build_scale_filter("h264_vaapi", 1440, 1080, 1920, 1080)
        self.assertIn("pad=1920:1080", vf)
        self.assertTrue(vf.endswith("hwupload"))


class TestBuildVideoPartCmd(unittest.TestCase):
    def _info(self, has_audio=True, w=1920, h=1080):
        return {"width": w, "height": h, "fps": 30.0, "vbitrate": 4_000_000,
                "has_audio": has_audio, "abitrate": 192_000 if has_audio else None}

    def _cmd(self, info, dst="part.mp4", family="h264", **kw):
        return clipctl.build_video_part_cmd(
            Path("in.mp4"), Path(dst), 1920, 1080, "libx264", [], info, family, **kw)

    def test_trim_seeks_and_limits(self):
        cmd = self._cmd(self._info(), trim=(5, 17))
        self.assertEqual(cmd[cmd.index("-ss") + 1], "5")
        self.assertEqual(cmd[cmd.index("-t") + 1], "12")

    def test_join_never_seeks_or_cuts(self):
        cmd = self._cmd(self._info())
        self.assertNotIn("-ss", cmd)
        self.assertNotIn("-t", cmd)

    def test_auto_follows_the_source(self):
        self.assertIn("-an", self._cmd(self._info(has_audio=False)))
        self.assertIn("aac", self._cmd(self._info()))

    def test_none_drops_audio_that_exists(self):
        self.assertIn("-an", self._cmd(self._info(), audio="none"))

    def test_silence_fills_only_the_silent_clips(self):
        filled = self._cmd(self._info(has_audio=False), audio="silence")
        self.assertIn(clipctl.SILENT_SRC, filled)
        self.assertIn("-shortest", filled)
        self.assertNotIn("-an", filled)
        untouched = self._cmd(self._info(), audio="silence")
        self.assertNotIn(clipctl.SILENT_SRC, untouched)
        self.assertNotIn("-shortest", untouched)

    def test_silence_input_lands_before_the_output_options(self):
        # -t has to sit after every -i or it truncates the silent input
        # instead of the part
        cmd = self._cmd(self._info(has_audio=False), audio="silence", trim=(0, 4))
        self.assertLess(cmd.index("-i"), cmd.index(clipctl.SILENT_SRC))
        self.assertLess(cmd.index(clipctl.SILENT_SRC), cmd.index("-t"))

    def test_vp9_family_uses_vp9_and_opus(self):
        cmd = self._cmd(self._info(), dst="part.webm", family="vp9")
        self.assertIn("libvpx-vp9", cmd)
        self.assertIn("libopus", cmd)
        self.assertNotIn("-movflags", cmd)

    def test_faststart_only_for_mp4_and_mov(self):
        self.assertIn("-movflags", self._cmd(self._info(), dst="part.mov"))
        self.assertNotIn("-movflags", self._cmd(self._info(), dst="part.mkv"))


class TestPromptAudioMode(unittest.TestCase):
    def _answer(self, infos, reply):
        original = clipctl.prompt_choice
        clipctl.prompt_choice = lambda *a, **k: reply
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                return clipctl.prompt_audio_mode(infos)
        finally:
            clipctl.prompt_choice = original

    def test_uniform_clips_ask_nothing(self):
        for infos in ([{"has_audio": True}] * 3, [{"has_audio": False}] * 3, []):
            with contextlib.redirect_stdout(io.StringIO()) as buf:
                self.assertEqual(clipctl.prompt_audio_mode(infos), "auto")
            self.assertEqual(buf.getvalue(), "")

    def test_mixed_clips_honor_the_answer(self):
        # desync issues with one clip with sound one without left alone the
        # concat drops the silent clip out of the audio timeline and every
        # later clips sound slides forward onto the wrong footage fuuuuuuuuuuuuuuuuuuuuuuuuck
        mixed = [{"has_audio": True}, {"has_audio": False}, {"has_audio": True}]
        self.assertEqual(self._answer(mixed, "1"), "silence")
        self.assertEqual(self._answer(mixed, "2"), "none")

    def test_every_answer_is_a_policy_the_builder_knows(self):
        info = {"width": 1920, "height": 1080, "fps": 30.0, "vbitrate": None,
                "has_audio": False, "abitrate": None}
        for mode in ("auto", "silence", "none"):
            cmd = clipctl.build_video_part_cmd(
                Path("in.mp4"), Path("p.mp4"), 1920, 1080, "libx264", [], info,
                "h264", audio=mode)
            self.assertTrue(("-an" in cmd) or ("-c:a" in cmd), mode)


class TestCopyJoinBlocker(unittest.TestCase):
    def _clip(self, name, sig=("v",), fps=30.0):
        return (1, Path(name), {"stream_sig": sig, "fps": fps})

    def test_identical_clips_can_be_copied(self):
        self.assertIsNone(clipctl.copy_join_blocker(
            [self._clip("1.mp4"), self._clip("2.mp4")]))

    def test_single_clip_is_trivially_copyable(self):
        self.assertIsNone(clipctl.copy_join_blocker([self._clip("1.mp4")]))

    def test_uppercase_extensions_still_match(self):
        self.assertIsNone(clipctl.copy_join_blocker(
            [self._clip("1.MP4"), self._clip("2.mp4")]))

    def test_float_noise_in_fps_is_not_a_mismatch(self):
        self.assertIsNone(clipctl.copy_join_blocker(
            [self._clip("1.mp4", fps=29.97), self._clip("2.mp4", fps=29.970003)]))

    def test_mixed_containers_block_the_copy(self):
        self.assertIn("containers", clipctl.copy_join_blocker(
            [self._clip("1.mp4"), self._clip("2.mkv")]))

    def test_mixed_streams_block_the_copy(self):
        self.assertIn("streams", clipctl.copy_join_blocker(
            [self._clip("1.mp4", sig=("v", "a")), self._clip("2.mp4", sig=("v",))]))

    def test_mixed_frame_rates_block_the_copy(self):
        self.assertIn("frame rates", clipctl.copy_join_blocker(
            [self._clip("1.mp4", fps=30.0), self._clip("2.mp4", fps=60.0)]))


class TestUniqueOutput(unittest.TestCase):
    def test_collision_numbering(self):
        with tempfile.TemporaryDirectory() as td:
            outdir = Path(td)
            src = Path("clip.mp4")
            first = clipctl.unique_output(outdir, src, ".mkv")
            self.assertEqual(first.name, "clip.mkv")
            first.write_bytes(b"x")
            second = clipctl.unique_output(outdir, src, ".mkv")
            self.assertEqual(second.name, "clip_2.mkv")
            second.write_bytes(b"x")
            third = clipctl.unique_output(outdir, src, ".mkv")
            self.assertEqual(third.name, "clip_3.mkv")

    def test_dotted_stems_survive(self):
        with tempfile.TemporaryDirectory() as td:
            out = clipctl.unique_output(Path(td), Path("my.cool.clip.mp4"), ".gif")
            self.assertEqual(out.name, "my.cool.clip.gif")

    def test_same_stem_in_one_batch_cannot_collide(self):
        # song.mp3 + song.m4a both converted to .wav used to be planned onto
        # the same song.wav and the second run silently ate the first
        with tempfile.TemporaryDirectory() as td:
            outdir = Path(td)
            taken = set()
            a = clipctl.unique_output(outdir, Path("song.m4a"), ".wav", taken)
            b = clipctl.unique_output(outdir, Path("song.mp3"), ".wav", taken)
            self.assertEqual(a.name, "song.wav")
            self.assertEqual(b.name, "song_2.wav")

    def test_batch_reservation_still_respects_the_disk(self):
        with tempfile.TemporaryDirectory() as td:
            outdir = Path(td)
            (outdir / "song.wav").write_bytes(b"x")
            taken = set()
            a = clipctl.unique_output(outdir, Path("song.m4a"), ".wav", taken)
            b = clipctl.unique_output(outdir, Path("song.mp3"), ".wav", taken)
            self.assertEqual([a.name, b.name], ["song_2.wav", "song_3.wav"])


class TestKindOf(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(clipctl.kind_of(Path("a.mp4")), "video")
        self.assertEqual(clipctl.kind_of(Path("a.MP4")), "video")
        self.assertEqual(clipctl.kind_of(Path("a.mp3")), "audio")
        self.assertEqual(clipctl.kind_of(Path("a.png")), "image")
        self.assertEqual(clipctl.kind_of(Path("a.txt")), "file")


class TestImageMaps(unittest.TestCase):
    def test_every_offered_target_has_an_encoder(self):
        for ext in clipctl.available_image_targets():
            self.assertIn(ext, clipctl.IMAGE_ENCODER_MAP, ext)

    def test_flatten_targets_have_pixfmt(self):
        for ext in (".jpg", ".jpeg", ".bmp", ".ppm"):
            self.assertIn(ext, clipctl.FLATTEN_PIXFMT, ext)


class TestEncoderListParsing(unittest.TestCase):
    def test_regex_matches_real_layout(self):
        m = clipctl._ENC_LINE_RE.match(
            " V....D h264_nvenc           NVIDIA NVENC H.264 encoder")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(2), "h264_nvenc")

    def test_parses_nonempty_set_without_legend_junk(self):
        # build independent... dont assert any specific encoder exists
        # non gpl builds lack libx264 just that parsing found real
        # names and didnt swallow the legend lines
        encs = clipctl._available_encoders()
        self.assertTrue(encs)
        self.assertNotIn("=", encs)


class TestNumberedFileContract(unittest.TestCase):
    def test_accepts_plain_positive_integers(self):
        for s in ("1", "2", "10", "42", "999"):
            self.assertIsNotNone(clipctl._CLIP_NUM_RE.fullmatch(s), s)

    def test_rejects_everything_the_readme_says_it_rejects(self):
        for s in ("01", "001", "0", "+1", "-1", " 1", "1 ", "２",
                  "clip1", "Clip 1", "1a", "1.5", ""):
            self.assertIsNone(clipctl._CLIP_NUM_RE.fullmatch(s), repr(s))

    def test_find_numbered_files_honors_the_contract(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            for name in ("1.mp4", "2.mkv", "01.mp4", "clip1.mp4", "0.mp4"):
                (d / name).write_bytes(b"x")
            found = clipctl.find_numbered_files(d, clipctl.VIDEO_EXTS)
            self.assertEqual([(n, p.name) for n, p in found],
                             [(1, "1.mp4"), (2, "2.mkv")])


class TestAudioCopyMap(unittest.TestCase):
    def test_copy_targets_are_offered_targets(self):
        for ext in clipctl.AUDIO_COPY_CODECS:
            self.assertIn(ext, clipctl.AUDIO_TARGETS, ext)


class TestPrintable(unittest.TestCase):
    def test_strips_escape_sequences(self):
        evil = "clip\x1b[31mRED\x1b[0m\x07.mp4"
        clean = clipctl.printable(evil)
        self.assertNotIn("\x1b", clean)
        self.assertNotIn("\x07", clean)
        self.assertTrue(clean.startswith("clip"))

    def test_leaves_normal_names_alone(self):
        for name in ("1.mp4", "Măciucă frags 2.mkv", "gameplay_🔥.mp4"):
            # emoji and the non ascii letters are not for decoration they are test data
            # to make sure that printable() does not fuck up filenames and other shit
            self.assertEqual(clipctl.printable(name), name)


class TestFmtCmd(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "posix quoting on this box")
    def test_posix_line_roundtrips(self):
        import shlex
        cmd = ["ffmpeg", "-i", "my clip.mp4", "out put.mkv"]
        self.assertEqual(shlex.split(clipctl._fmt_cmd(cmd)), cmd)


class TestClipperContainers(unittest.TestCase):
    def test_families_are_known(self):
        for ext, family in clipctl.CLIPPER_CONTAINERS.items():
            self.assertIn(family, ("h264", "vp9"), ext)

    def test_webm_is_vp9(self):
        self.assertEqual(clipctl.CLIPPER_CONTAINERS[".webm"], "vp9")


if __name__ == "__main__":
    unittest.main(verbosity=2)
