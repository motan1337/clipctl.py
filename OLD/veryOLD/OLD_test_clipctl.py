#!/usr/bin/env python3
"""
test_clipctl.py, regression tests for clipctl if i fuck up shits (motan1337 in this case lol,
or maybe u the one that is messing up with my code?)

Run with:  python3 -m unittest test_clipctl -v (linux)
           python -m unittest test_clipctl -v (windows)
No dependencies beyond the stdlib (and ffmpeg on PATH, which clipctl
itself already requires at import time).
GREAT SUCCESS! VERY NICE!
"""

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
        self.assertIn("hwupload", vf)
        self.assertIn("scale_vaapi", vf)


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

    def test_regex_ignores_legend_indirectly(self):
        self.assertIn("libx264", clipctl._available_encoders())
        self.assertNotIn("=", clipctl._available_encoders())


class TestClipperContainers(unittest.TestCase):
    def test_families_are_known(self):
        for ext, family in clipctl.CLIPPER_CONTAINERS.items():
            self.assertIn(family, ("h264", "vp9"), ext)

    def test_webm_is_vp9(self):
        self.assertEqual(clipctl.CLIPPER_CONTAINERS[".webm"], "vp9")


if __name__ == "__main__":
    unittest.main(verbosity=2)