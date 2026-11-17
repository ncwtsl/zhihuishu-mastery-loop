"""Shared configuration for the zhihuishu mastery driver.

Course / class ids and the CDP port are read from environment variables so the
same scripts work for any student and any term:

    ZHS_COURSE=2092834400809041920   # the long id in the course URL
    ZHS_CLASS=333872                 # the trailing term/class id
    ZHS_PORT=9222                    # remote debugging port of the Edge we drive
    ZHS_DATA=<dir>                   # bank + logs; defaults to ../data

URLs are assembled from these, so nothing is hard-coded per course.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
COURSE = os.environ.get("ZHS_COURSE", "2092834400809041920")
CLASS = os.environ.get("ZHS_CLASS", "333872")
PORT = int(os.environ.get("ZHS_PORT", "9222"))

DATA = os.environ.get("ZHS_DATA") or os.path.join(os.path.dirname(HERE), "data")
os.makedirs(DATA, exist_ok=True)

BASE = "https://ai-smart-course-student-pro.zhihuishu.com"
STUDY_URL = "%s/singleCourse/knowledgeStudy/%s/%s" % (BASE, COURSE, CLASS)
LEARN_URL = "%s/learnPage/%s/%%s/%s?catalogActiveTab=personal" % (BASE, COURSE, CLASS)
PREVIEW_URL = "%s/examPreview/%s/%%s/%%s/%%s/%s" % (BASE, COURSE, CLASS)

BANK = os.path.join(DATA, "answers.json")
DOM_MASTERY = os.path.join(DATA, "dom_mastery.json")
LOG = os.path.join(DATA, "batchall.log")


def path(name):
    return os.path.join(DATA, name)


def dump(obj, name):
    with open(path(name), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def load(name, default=None):
    try:
        with open(path(name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default
