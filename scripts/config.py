"""Shared configuration for the zhihuishu mastery driver.

Everything that differs between a student, a term and a machine comes from the
environment, so the same scripts work for any course and any port:

    ZHS_COURSE=2092834400809041920   # the long id in the course URL
    ZHS_CLASS=333872                 # the trailing term/class id
    ZHS_PORT=9222                    # remote debugging port of the Edge we drive
    ZHS_DATA=<dir>                   # bank + logs; defaults to ../data

Tunables (all optional):

    ZHS_TARGET=100                   # mastery that counts as done
    ZHS_MAXR=9                       # paper attempts per knowledge point
    ZHS_PROBE=12                     # extra oracle attempts allowed per point
    ZHS_JITTER=0.4                   # seconds of randomisation added per action
    ZHS_GUESS=A                      # fallback letter for a never-seen question
"""
import json
import os
import random
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
COURSE = os.environ.get("ZHS_COURSE", "2092834400809041920")
CLASS = os.environ.get("ZHS_CLASS", "333872")
PORT = int(os.environ.get("ZHS_PORT", "9222"))

TARGET = float(os.environ.get("ZHS_TARGET", "100"))
MAXR = int(os.environ.get("ZHS_MAXR", "9"))
PROBE = int(os.environ.get("ZHS_PROBE", "12"))
JITTER = float(os.environ.get("ZHS_JITTER", "0.4"))
GUESS = (os.environ.get("ZHS_GUESS", "A") or "A")[:1].upper()

DATA = os.environ.get("ZHS_DATA") or os.path.join(os.path.dirname(HERE), "data")
os.makedirs(DATA, exist_ok=True)

BASE = "https://ai-smart-course-student-pro.zhihuishu.com"
STUDY_URL = "%s/singleCourse/knowledgeStudy/%s/%s" % (BASE, COURSE, CLASS)
LEARN_URL = "%s/learnPage/%s/%%s/%s?catalogActiveTab=personal" % (BASE, COURSE, CLASS)
PREVIEW_URL = "%s/examPreview/%s/%%s/%%s/%%s/%s" % (BASE, COURSE, CLASS)

BANK = os.path.join(DATA, "answers.json")
DOM_MASTERY = os.path.join(DATA, "dom_mastery.json")
LOG = os.path.join(DATA, "batchall.log")
SUMMARY = os.path.join(DATA, "summary.json")
AUDIT = os.path.join(DATA, "audit.md")


def path(name):
    return os.path.join(DATA, name)


def sleep(seconds):
    """Sleep with a little jitter.

    Every action in the old driver used a fixed constant (700 ms, 1.5 s, 2.5 s).
    Fixed cadence is the most recognisable automation fingerprint there is, and
    it also lines up badly when the page happens to render slowly.
    """
    if seconds > 0:
        seconds += random.uniform(0, max(0.0, JITTER))
    time.sleep(seconds)


def dump(obj, name):
    target = name if os.path.isabs(name) else path(name)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, target)


def load(name, default=None):
    target = name if os.path.isabs(name) else path(name)
    try:
        with open(target, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default
