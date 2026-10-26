from pathlib import Path

DIR_RESOURCES = Path(__file__).parent
FILE_CONFIG = DIR_RESOURCES / "config.json"
DIR_TEMPLATES = DIR_RESOURCES / "templates"
FILE_COMMENT = DIR_RESOURCES / "comment.txt"
FILE_COMMENT_LATE_REVIEWS = DIR_RESOURCES / "comment-late-reviews.txt"
FILE_VARIABLES = DIR_RESOURCES / "variables.txt"  # what each template placeholder means
FILE_AI_PHRASES = DIR_RESOURCES / "ai_phrases.txt"
FILE_AI_WORDS = DIR_RESOURCES / "ai_words.txt"
