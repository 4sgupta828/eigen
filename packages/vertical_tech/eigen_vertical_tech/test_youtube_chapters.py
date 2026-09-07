"""YouTube as a chapter source: the description is public even though the captions are not."""
from __future__ import annotations

import asyncio

from eigen_vertical_tech import show_notes_doc as D
from eigen_vertical_tech.connectors.youtube_chapters import (CHANNELS, YoutubeChaptersConnector,
                                                             parse_channel)

FEED = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/">
  <title>Y Combinator</title>
  <entry>
    <yt:videoId>abc123XYZ_1</yt:videoId>
    <title>Why The Harness Matters More Than The Model | YC Paper Club</title>
    <published>2026-09-02T17:00:00+00:00</published>
    <media:group>
      <media:description>Notes:
0:00 Cold open on the crash
4:27 Building an auto-researcher by accident
13:00 Why the Series A nearly killed us
Subscribe for more.</media:description>
    </media:group>
  </entry>
  <entry>
    <yt:videoId>nochapters1</yt:videoId>
    <title>A short clip with no chapters</title>
    <published>2026-09-01T17:00:00+00:00</published>
    <media:group><media:description>Just a clip.</media:description></media:group>
  </entry>
</feed>"""


def test_the_description_lives_under_media_group():
    # An earlier probe read the entry's own <description>, found nothing, and nearly wrote YouTube
    # off entirely. The text is one level down, inside <media:group>.
    recs = parse_channel(FEED, "Y Combinator")
    assert len(recs) == 2
    assert "auto-researcher" in recs[0]["summary"]
    assert recs[0]["link"] == "https://www.youtube.com/watch?v=abc123XYZ_1"
    assert recs[0]["publication"] == "Y Combinator"


def test_chapters_deep_link_into_the_creators_own_video():
    recs = parse_channel(FEED, "Y Combinator")
    md = D.to_markdown(recs[0])
    assert "watch?v=abc123XYZ_1&t=267" in md          # 4:27 → 267 seconds
    assert "Nothing here is a quotation" in md        # the pointer register, same as a podcast


def test_a_video_with_no_chapters_is_never_indexed():
    recs = parse_channel(FEED, "Y Combinator")
    c = YoutubeChaptersConnector(videos=recs)
    ents = asyncio.run(c.discover_entities({}))
    assert [e.native_id for e in ents] == ["youtube:abc123XYZ_1"]


def test_the_channel_list_is_pinned_by_id_not_handle():
    assert CHANNELS, "the allowlist must not be empty"
    for cid, name in CHANNELS.items():
        assert cid.startswith("UC") and len(cid) >= 20, cid   # a handle can be reassigned; an id cannot
        assert name
