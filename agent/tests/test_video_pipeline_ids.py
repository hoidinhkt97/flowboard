import re

from flowboard.services.video_pipeline.ids import new_short_id


def test_short_id_format():
    sid = new_short_id()
    assert re.fullmatch(r"vpr_[0-9a-z]{5}", sid), sid


def test_short_id_unique_enough():
    seen = {new_short_id() for _ in range(2000)}
    assert len(seen) > 1990  # collisions vanishingly rare
