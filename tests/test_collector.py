from types import SimpleNamespace as NS

from aamas_review_monitor.collector import collect

VENUE = "ifaamas.org/AAMAS/2027/Conference"
SUB = f"{VENUE}/Submission"


def reply(kind, sig, **content):
    return {
        "invitations": [f"{SUB}7/-/{kind}"],
        "signatures": [f"{SUB}7/{sig}"],
        "content": {k: {"value": v} for k, v in content.items()},
    }


class FakeClient:
    """Mimics the openreview-py v2 calls the collector makes; no network."""

    profile = NS(id="~Sac_Chair1")

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
            reply("Official_Comment", "Area_Chair_zz", comment="please discuss"),
        ]
        return [NS(id="abc", number=7, details={"replies": replies}), NS(id="x", number=70)]


def test_collect_keeps_only_process_metadata():
    snap = collect(
        FakeClient(),
        {
            "venue_id": VENUE,
            "url_forum": "https://openreview.net/forum?id=",
            "field_rating": "rating",
            "field_confidence": "confidence",
        },
    )
    assert snap["papers"] == [
        {
            "number": 7,
            "url": "https://openreview.net/forum?id=abc",
            "spcs": ["~Spc_One1"],
            "reviewers": ["~Rev_A1", "~Rev_B1", "~Rev_C1"],
            "reviews": [
                {"reviewer": "~Rev_A1", "rating": 6, "confidence": 4, "words": 203},
                {
                    "reviewer": f"{SUB}7/Reviewer_hidden",
                    "rating": 3,
                    "confidence": None,
                    "words": 1,
                },
            ],
            "meta_review": False,
            "comments": 1,
        }
    ]
