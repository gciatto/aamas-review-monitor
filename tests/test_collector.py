from types import SimpleNamespace as NS

from aamas_review_monitor.collector import fetch, summarize

VENUE = "ifaamas.org/AAMAS/2027/Conference"
SUB = f"{VENUE}/Submission"
CONFIG = {
    "venue_id": VENUE,
    "url_forum": "https://openreview.net/forum?id=",
    "field_rating": "rating",
    "field_confidence": "confidence",
}


def reply(kind, sig, **content):
    return {
        "invitations": [f"{SUB}7/-/{kind}"],
        "signatures": [f"{SUB}7/{sig}"],
        "content": {k: {"value": v} for k, v in content.items()},
    }


class FakeClient:
    """Mimics the openreview-py v2 calls the app makes; no network, records messages."""

    profile = NS(id="~Sac_Chair1")

    def __init__(self):
        self.messages = []
        self.downloads = []

    def get_group(self, id):
        return NS(content={"area_chairs_name": {"value": "Area_Chairs"}})

    def get_all_groups(self, member=None, prefix=None):
        if member:  # SAC on 7; also reviewer of 70, which must be ignored
            return [NS(id=f"{SUB}7/Senior_Area_Chairs"), NS(id=f"{SUB}70/Reviewers")]
        assert prefix == f"{SUB}7/"
        return [
            NS(id=f"{SUB}7/Area_Chairs", members=[f"{SUB}7/Area_Chair_9jqi"]),
            NS(id=f"{SUB}7/Area_Chair_9jqi", members=["~Spc_One1"]),
            NS(id=f"{SUB}7/Reviewers", members=[f"{SUB}7/Reviewer_aB3x", "~Rev_B1", "~Rev_C1"]),
            NS(id=f"{SUB}7/Reviewer_aB3x", members=["~Rev_A1"]),
            NS(id=f"{SUB}7/Reviewer_hidden", members=[]),
        ]

    def get_all_notes(self, invitation, details):
        assert invitation == f"{VENUE}/-/Submission" and details == "replies"
        replies = [
            reply(
                "Official_Review",
                "Reviewer_aB3x",
                rating="6: weak accept",
                confidence=4,
                summary="word " * 200,
            ),
            reply("Official_Review", "Reviewer_hidden", rating=3, summary="short"),
            reply("Meta_Review", "Area_Chair_9jqi", metareview="fine"),
            reply("Official_Comment", "Area_Chair_9jqi", comment="please discuss"),
        ]
        content = {"title": {"value": "A Paper"}, "pdf": {"value": "/pdf/v1.pdf"}}
        return [
            NS(id="abc", number=7, content=content, details={"replies": replies}),
            NS(id="x", number=70, content={}, details=None),
        ]

    def get_attachment(self, field_name, id):
        self.downloads.append((field_name, id))
        return b"%PDF"

    def post_message(self, *args, **kwargs):
        self.messages.append((args, kwargs))


def test_fetch_and_summarize_keep_only_process_metadata():
    (record,) = fetch(FakeClient(), CONFIG)
    assert record["number"] == 7 and record["content"]["title"]["value"] == "A Paper"
    assert summarize(record, CONFIG) == {
        "number": 7,
        "url": "https://openreview.net/forum?id=abc",
        "spcs": ["~Spc_One1"],
        "reviewers": ["~Rev_A1", "~Rev_B1", "~Rev_C1"],
        "reviews": [
            {"reviewer": "~Rev_A1", "rating": 6, "confidence": 4, "words": 203},
            {"reviewer": f"{SUB}7/Reviewer_hidden", "rating": 3, "confidence": None, "words": 1},
        ],
        "meta_review": True,
        "comments": 1,
    }
