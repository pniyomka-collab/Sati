# -*- coding: utf-8 -*-
"""
สมาธิ · Sati — Meditation Timer & Journal
=========================================
Single-file Flask app (app.py) + TailwindCSS (CDN)

รัน:  pip install flask
      python app.py
เปิด: http://127.0.0.1:5000

ข้อมูลทั้งหมดเก็บในไฟล์ meditation.db (SQLite) ข้างๆ app.py
"""

import io
import sys
import csv
import json
import math
import os
import sqlite3
from datetime import datetime, date, timedelta

from flask import Flask, Response, g, jsonify, request

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("SATI_DB", os.path.join(APP_DIR, "meditation.db"))

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False


# ─────────────────────────────────────────────────────────────
#  ฐานข้อมูล / Database
# ─────────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    day             TEXT NOT NULL,
    hour            INTEGER NOT NULL DEFAULT 0,
    planned_seconds INTEGER NOT NULL DEFAULT 0,
    actual_seconds  INTEGER NOT NULL DEFAULT 0,
    completed       INTEGER NOT NULL DEFAULT 0,
    technique       TEXT    NOT NULL DEFAULT 'anapanasati',
    mood_before     INTEGER,
    mood_after      INTEGER,
    rating          INTEGER,
    notes           TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS custom_content (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL,          -- 'opening' | 'praise'
    title_th   TEXT NOT NULL DEFAULT '',
    title_en   TEXT NOT NULL DEFAULT '',
    body_th    TEXT NOT NULL DEFAULT '',
    body_en    TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    con.commit()
    con.close()


# ─────────────────────────────────────────────────────────────
#  ค่าตั้งต้น / Default settings  (ทุกอย่างปรับแต่งได้)
# ─────────────────────────────────────────────────────────────
DEFAULT_SETTINGS = {
    "lang": "th",
    "theme": "dark",
    "accent": "emerald",
    "fontScale": 1.0,

    # เวลา
    "duration": 15,            # นาที
    "prepSeconds": 10,         # เวลาเตรียมตัวก่อนระฆังเริ่ม
    "intervalBell": 0,         # ระฆังเตือนทุก ๆ N นาที (0 = ปิด)
    "closingSeconds": 60,      # ช่วงแผ่เมตตาหลังระฆังจบ (0 = ปิด)
    "countUp": False,          # นับขึ้นแทนนับถอยหลัง
    "openEnded": False,        # นั่งแบบไม่จำกัดเวลา
    "presets": [5, 10, 15, 20, 30, 45, 60],

    # เสียง
    "startBell": "bowl",
    "endBell": "bowl",
    "intervalSound": "chime",
    "startStrikes": 3,
    "endStrikes": 3,
    "volume": 0.7,
    "ambience": "none",        # none | rain | ocean | forest | hum
    "ambienceVolume": 0.25,

    # ประสบการณ์
    "showOpening": True,
    "openingId": "random",
    "showPraise": True,
    "askMood": True,
    "showClock": True,
    "keepAwake": True,
    "breathGuide": True,       # วงกลมนำลมหายใจ
    "breathIn": 4,
    "breathOut": 6,
    "technique": "anapanasati",

    # เป้าหมาย / เกม
    "dailyGoal": 20,           # นาที/วัน
    "weeklyGoalDays": 5,
}


def load_settings():
    db = get_db()
    row = db.execute("SELECT value FROM settings WHERE key='app'").fetchone()
    data = dict(DEFAULT_SETTINGS)
    if row:
        try:
            data.update(json.loads(row["value"]))
        except (ValueError, TypeError):
            pass
    return data


def save_settings(patch):
    db = get_db()
    data = load_settings()
    data.update(patch or {})
    db.execute(
        "INSERT INTO settings(key, value) VALUES('app', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (json.dumps(data, ensure_ascii=False),),
    )
    db.commit()
    return data


# ─────────────────────────────────────────────────────────────
#  คำกล่าวนำการนั่งสมาธิ / Opening words
# ─────────────────────────────────────────────────────────────
OPENINGS = [
    {
        "id": "namo",
        "title_th": "บทบูชาพระรัตนตรัย",
        "title_en": "Homage to the Buddha",
        "body_th": "นะโม ตัสสะ ภะคะวะโต อะระหะโต สัมมาสัมพุทธัสสะ (๓ จบ)\n\nขอนอบน้อมแด่พระผู้มีพระภาคเจ้า พระองค์นั้น\nซึ่งเป็นผู้ไกลจากกิเลส ตรัสรู้ชอบได้โดยพระองค์เอง",
        "body_en": "Namo tassa bhagavato arahato samma-sambuddhassa (3 times)\n\nHomage to the Blessed One, the Worthy One,\nthe Perfectly Self-Awakened One.",
    },
    {
        "id": "intention",
        "title_th": "ตั้งเจตนาก่อนภาวนา",
        "title_en": "Setting the Intention",
        "body_th": "ในช่วงเวลาต่อจากนี้ ข้าพเจ้าจะวางภาระทั้งปวงลงชั่วคราว\nไม่คิดถึงอดีต ไม่กังวลถึงอนาคต\nมีเพียงลมหายใจนี้ และใจที่รู้ลมหายใจนี้\n\nขอให้การภาวนาครั้งนี้ เป็นไปเพื่อความสงบ\nเพื่อปัญญา และเพื่อประโยชน์สุขแก่สรรพสัตว์ทั้งหลาย",
        "body_en": "For the time that follows, I set down every burden.\nNo dwelling in the past, no reaching for the future.\nOnly this breath, and the mind that knows this breath.\n\nMay this practice lead to peace, to clear seeing,\nand to the welfare and happiness of all beings.",
    },
    {
        "id": "metta",
        "title_th": "แผ่เมตตาก่อนนั่ง",
        "title_en": "Metta Before Sitting",
        "body_th": "สัพเพ สัตตา อะเวรา โหนตุ\nขอสัตว์ทั้งหลายทั้งปวง จงอย่าได้มีเวรต่อกันเลย\nอัพยาปัชฌา โหนตุ — จงอย่าได้เบียดเบียนกันเลย\nอะนีฆา โหนตุ — จงอย่าได้มีทุกข์กายทุกข์ใจเลย\nสุขี อัตตานัง ปะริหะรันตุ — จงมีความสุข รักษาตนให้พ้นจากทุกข์ภัยเถิด",
        "body_en": "May all beings be free from enmity.\nMay all beings be free from harm.\nMay all beings be free from suffering of body and mind.\nMay all beings care for themselves with ease and happiness.",
    },
    {
        "id": "anapana",
        "title_th": "คำนำสติสู่ลมหายใจ",
        "title_en": "Turning Toward the Breath",
        "body_th": "นั่งตัวตรง ดำรงสติให้มั่น\nปล่อยไหล่ลง คลายกราม คลายหน้าผาก\n\nหายใจเข้ายาว ก็รู้ว่าหายใจเข้ายาว\nหายใจออกยาว ก็รู้ว่าหายใจออกยาว\n\nไม่ต้องบังคับลม เพียงรู้ลมตามที่เป็น\nเมื่อใจเผลอไป รู้ว่าเผลอ แล้วพากลับมาอย่างอ่อนโยน\nการกลับมาได้ — นั่นแหละคือการภาวนา",
        "body_en": "Sit upright. Let mindfulness stand firm.\nSoften the shoulders, the jaw, the brow.\n\nBreathing in long, one knows: breathing in long.\nBreathing out long, one knows: breathing out long.\n\nDo not control the breath, simply know it as it is.\nWhen the mind wanders, know that it wandered,\nand lead it home gently. The returning IS the practice.",
    },
    {
        "id": "short",
        "title_th": "คำกล่าวสั้น (สำหรับผู้เริ่มต้น)",
        "title_en": "A Short Opening (for Beginners)",
        "body_th": "ช่วงเวลานี้ เป็นของฉัน\nไม่มีอะไรต้องทำ ไม่มีที่ไหนต้องไป\nเพียงนั่งอยู่ตรงนี้ กับลมหายใจหนึ่งครั้ง\nแล้วอีกหนึ่งครั้ง",
        "body_en": "This moment belongs to me.\nNothing to do. Nowhere to go.\nJust sitting here with one breath,\nand then one more.",
    },
    {
        "id": "silent",
        "title_th": "เงียบ ไม่ต้องมีคำกล่าว",
        "title_en": "Silence, No Words",
        "body_th": "หลับตา\nหายใจเข้า...\nหายใจออก...",
        "body_en": "Close the eyes.\nBreathe in...\nBreathe out...",
    },
]

# ─────────────────────────────────────────────────────────────
#  คำชม / Words of encouragement
# ─────────────────────────────────────────────────────────────
PRAISE = [
    {"th": "เยี่ยมมาก! การที่คุณมานั่งในวันนี้ สำคัญกว่าคุณภาพของการนั่งเสียอีก",
     "en": "Wonderful. That you showed up today matters more than how the sitting went."},
    {"th": "ใจฟุ้งบ้างเป็นเรื่องธรรมดา ทุกครั้งที่คุณรู้ตัวและกลับมา คือสติที่แข็งแรงขึ้นหนึ่งครั้ง",
     "en": "A wandering mind is normal. Every return is one more rep for your mindfulness."},
    {"th": "คุณเพิ่งให้ของขวัญกับตัวเอง — ความสงบที่ไม่มีใครซื้อให้ได้",
     "en": "You just gave yourself something no one can buy for you: a little stillness."},
    {"th": "ต้นไม้ไม่โตในวันเดียว การภาวนาก็เช่นกัน วันนี้คุณรดน้ำแล้ว",
     "en": "A tree does not grow in a day. Today you watered it. That is enough."},
    {"th": "ไม่มีการนั่งที่ล้มเหลว มีแต่การนั่งที่ได้เรียนรู้ต่างกัน",
     "en": "There is no failed sitting, only sittings that teach different lessons."},
    {"th": "ลมหายใจรอคุณอยู่เสมอ และวันนี้คุณกลับมาหามันแล้ว",
     "en": "The breath is always waiting. Today, you came back to it."},
    {"th": "ความสม่ำเสมอชนะความสมบูรณ์แบบ — และคุณกำลังสร้างความสม่ำเสมอ",
     "en": "Consistency beats perfection, and you are building consistency."},
    {"th": "ขอชื่นชมความตั้งใจของคุณ สาธุ 🙏",
     "en": "Well done. Your effort is worthy of respect. 🙏"},
    {"th": "หนึ่งลมหายใจที่รู้ตัว มีค่ากว่าหนึ่งชั่วโมงที่ลอยไป",
     "en": "One conscious breath is worth more than an hour of drifting."},
    {"th": "คุณกำลังฝึกสิ่งที่ยากที่สุดในโลก คือการอยู่กับตัวเองอย่างสงบ",
     "en": "You are practicing the hardest skill there is: being at peace with yourself."},
    {"th": "จิตที่ฝึกแล้ว นำสุขมาให้ — วันนี้คุณฝึกมันแล้วหนึ่งครั้ง",
     "en": "A trained mind brings happiness. Today you trained it once more."},
    {"th": "เก่งมาก! พรุ่งนี้มาต่ออีกนะ แม้เพียง ๕ นาทีก็ยังดี",
     "en": "Great work. Come back tomorrow, even five minutes counts."},
]

# ─────────────────────────────────────────────────────────────
#  บทเรียน อานาปานสติ / Learning content
# ─────────────────────────────────────────────────────────────
LESSONS = [
    {
        "id": "what",
        "icon": "🌬️",
        "title_th": "อานาปานสติคืออะไร",
        "title_en": "What is Anapanasati?",
        "body_th": "อานาปานสติ (ānāpānasati) แปลตรงตัวว่า “สติกำหนดลมหายใจเข้า-ออก” เป็นกรรมฐานที่พระพุทธเจ้าทรงสรรเสริญมากที่สุด และทรงใช้เองในคืนตรัสรู้\n\nหัวใจของมันเรียบง่ายมาก: ใช้ลมหายใจเป็น “บ้าน” ของจิต เมื่อจิตออกจากบ้าน เราก็พากลับมา ทำอย่างนี้ซ้ำ ๆ จนจิตอยู่บ้านได้นานขึ้นเรื่อย ๆ\n\nลมหายใจเหมาะเป็นอารมณ์กรรมฐานเพราะ (๑) มีอยู่กับเราตลอดเวลา (๒) อยู่ในปัจจุบันเสมอ (๓) สะท้อนสภาวะจิต เมื่อจิตสงบลมก็ละเอียด",
        "body_en": "Anapanasati literally means “mindfulness of in-and-out breathing.” It is the meditation the Buddha praised most highly, and the one he himself used on the night of his awakening.\n\nThe heart of it is simple: the breath is the mind's home. When the mind leaves home, we bring it back. We repeat this until the mind can stay home longer and longer.\n\nThe breath is an ideal object because (1) it is always with us, (2) it is always in the present, and (3) it mirrors the mind: as the mind calms, the breath refines.",
    },
    {
        "id": "posture",
        "icon": "🧘",
        "title_th": "ท่านั่ง ๗ จุด",
        "title_en": "The Seven Points of Posture",
        "body_th": "ท่านั่งที่ดีคือท่าที่ “ตื่นตัวแต่ผ่อนคลาย” ไม่ต้องขัดสมาธิเพชรก็ได้ นั่งเก้าอี้ได้เช่นกัน\n\n๑. ฐานมั่นคง — ขัดสมาธิ หรือนั่งเก้าอี้ให้เท้าแตะพื้น\n๒. หลังตรงตามธรรมชาติ — เหมือนเหรียญวางซ้อนกัน ไม่เกร็ง ไม่งอ\n๓. มือวางสบาย — บนตัก หรือบนเข่า\n๔. ไหล่ผ่อนลง เปิดอก\n๕. คางเก็บเล็กน้อย ท้ายทอยยืด\n๖. ตาหลับเบา ๆ หรือทอดสายตาลงต่ำ\n๗. ลิ้นแตะเพดานปาก กรามคลาย ยิ้มบาง ๆ",
        "body_en": "Good posture is “alert yet relaxed.” You do not need the full lotus, a chair works perfectly well.\n\n1. Stable base: cross-legged, or feet flat on the floor.\n2. Spine naturally upright, like coins stacked. Not rigid, not slumped.\n3. Hands resting easily on lap or knees.\n4. Shoulders released, chest open.\n5. Chin slightly tucked, back of the neck long.\n6. Eyes softly closed, or gazing down.\n7. Tongue on the palate, jaw loose, a faint smile.",
    },
    {
        "id": "howto",
        "icon": "🪜",
        "title_th": "เริ่มต้นอย่างไร (ทีละขั้น)",
        "title_en": "How to Begin, Step by Step",
        "body_th": "๑. ตั้งเวลา เริ่มที่ ๕–๑๐ นาทีก่อน อย่าเพิ่งโลภ\n๒. หายใจลึก ๓ ครั้ง เพื่อบอกร่างกายว่า “ถึงเวลาพักแล้ว”\n๓. ปล่อยลมหายใจให้เป็นธรรมชาติ ไม่ต้องบังคับ\n๔. หาจุดสัมผัสลม — ปลายจมูก เหนือริมฝีปาก หรือท้องที่พองยุบ เลือกจุดเดียวแล้วอยู่กับจุดนั้น\n๕. รู้ลมเข้า รู้ลมออก ถ้าใจฟุ้งมาก ลองนับ ๑–๑๐ แล้วเริ่มใหม่\n๖. เมื่อรู้ตัวว่าเผลอคิด — ไม่ต้องดุตัวเอง พูดในใจว่า “คิดหนอ” แล้วกลับมาที่ลม\n๗. ระฆังดัง ค่อย ๆ ลืมตา อย่ารีบลุก แผ่เมตตาสักครู่",
        "body_en": "1. Set a timer. Start with 5-10 minutes. Do not be greedy.\n2. Take three deep breaths to tell the body: it is time to rest.\n3. Let the breath return to its natural rhythm. No control.\n4. Find one touch-point: nostrils, upper lip, or the rise and fall of the belly. Choose one and stay there.\n5. Know the in-breath, know the out-breath. If very scattered, count 1-10, then restart.\n6. When you notice thinking, do not scold yourself. Note “thinking,” and return to the breath.\n7. When the bell sounds, open the eyes slowly. Do not rush up. Offer a moment of goodwill.",
    },
    {
        "id": "hindrance",
        "icon": "🌊",
        "title_th": "นิวรณ์ ๕ — อุปสรรคที่ทุกคนเจอ",
        "title_en": "The Five Hindrances",
        "body_th": "นิวรณ์คือสิ่งกั้นจิตไม่ให้สงบ ทุกคนเจอ ไม่ใช่ความผิดของคุณ\n\n๑. กามฉันทะ — ใจไหลไปหาสิ่งที่อยากได้ → รู้ทันว่า “อยาก” แล้วกลับมาที่ลม\n๒. พยาบาท — หงุดหงิด ขุ่นเคือง → แผ่เมตตาให้ตัวเองก่อน\n๓. ถีนมิทธะ — ง่วง ซึม → ลืมตาครึ่งหนึ่ง ยืดหลัง หายใจแรงขึ้น\n๔. อุทธัจจกุกกุจจะ — ฟุ้งซ่าน กังวล → ลองนับลมหายใจ หรือหายใจออกให้ยาวขึ้น\n๕. วิจิกิจฉา — สงสัยว่า “ทำถูกไหม” → ถ้ายังรู้ลมอยู่ แปลว่าถูกแล้ว",
        "body_en": "Hindrances are what block the mind from settling. Everyone meets them. They are not your fault.\n\n1. Sensual desire, the mind runs toward what it wants → note “wanting,” return.\n2. Ill will, irritation and resentment → send goodwill to yourself first.\n3. Sloth and torpor, drowsiness → open the eyes halfway, lengthen the spine, breathe stronger.\n4. Restlessness and worry → count the breaths, or make the out-breath longer.\n5. Doubt, “am I doing this right?” → if you know the breath, you are doing it right.",
    },
    {
        "id": "tetrads",
        "icon": "◍",
        "title_th": "อานาปานสติ ๑๖ ขั้น (๔ หมวด)",
        "title_en": "The 16 Steps in Four Tetrads",
        "body_th": "จากอานาปานสติสูตร — ผู้เริ่มต้นฝึกหมวดที่ ๑ ให้ชำนาญก่อนก็พอ\n\n【กายานุปัสสนา — ฐานกาย】\n๑. หายใจเข้า-ออกยาว ก็รู้\n๒. หายใจเข้า-ออกสั้น ก็รู้\n๓. รู้กองลมทั้งหมด (ต้น-กลาง-ปลาย)\n๔. ทำกายสังขารให้ระงับ (ลมละเอียดลง กายสงบ)\n\n【เวทนานุปัสสนา — ฐานเวทนา】\n๕. รู้ปีติ\n๖. รู้สุข\n๗. รู้จิตตสังขาร (เวทนา-สัญญาที่ปรุงจิต)\n๘. ทำจิตตสังขารให้ระงับ\n\n【จิตตานุปัสสนา — ฐานจิต】\n๙. รู้จิต\n๑๐. ทำจิตให้บันเทิง\n๑๑. ทำจิตให้ตั้งมั่น\n๑๒. ทำจิตให้ปล่อยวาง\n\n【ธัมมานุปัสสนา — ฐานธรรม】\n๑๓. พิจารณาความไม่เที่ยง\n๑๔. พิจารณาความคลายกำหนัด\n๑๕. พิจารณาความดับ\n๑๖. พิจารณาความสลัดคืน",
        "body_en": "From the Anapanasati Sutta. Beginners need only master the first tetrad.\n\n【Body】\n1. Breathing in/out long, one knows.\n2. Breathing in/out short, one knows.\n3. Sensitive to the whole breath-body.\n4. Calming the bodily formation.\n\n【Feeling】\n5. Sensitive to rapture.\n6. Sensitive to pleasure.\n7. Sensitive to the mental formation.\n8. Calming the mental formation.\n\n【Mind】\n9. Sensitive to the mind.\n10. Gladdening the mind.\n11. Steadying the mind.\n12. Releasing the mind.\n\n【Dhamma】\n13. Contemplating impermanence.\n14. Contemplating fading away.\n15. Contemplating cessation.\n16. Contemplating relinquishment.",
    },
    {
        "id": "after",
        "icon": "🪷",
        "title_th": "หลังออกจากสมาธิ",
        "title_en": "After the Sitting",
        "body_th": "อย่ารีบลุก ให้เวลากับ ๓ อย่างนี้\n\n๑. สังเกต — ตอนนี้กายรู้สึกอย่างไร ใจรู้สึกอย่างไร ต่างจากก่อนนั่งไหม\n๒. แผ่เมตตา — เริ่มจากตัวเอง แล้วขยายไปคนที่รัก คนที่เฉย ๆ คนที่ไม่ถูกกัน และสรรพสัตว์\n๓. บันทึก — จดสั้น ๆ ว่าวันนี้เป็นอย่างไร การจดทำให้เห็นแนวโน้มระยะยาว และเป็นกำลังใจ\n\nแล้วพยายามพาความรู้ตัวนี้ติดตัวไปในกิจวัตร เช่น รู้ลมหายใจตอนล้างจาน เดิน หรือรอไฟแดง",
        "body_en": "Do not rush. Give three things a moment.\n\n1. Notice: how does the body feel now? The mind? Different from before?\n2. Metta: begin with yourself, then a loved one, a neutral person, a difficult person, all beings.\n3. Record: a short note. Journaling reveals long-term trends and keeps you encouraged.\n\nThen carry that awareness into the day: know the breath while washing dishes, walking, or waiting at a red light.",
    },
    {
        "id": "plan",
        "icon": "📅",
        "title_th": "ตารางฝึก ๔ สัปดาห์สำหรับผู้เริ่มต้น",
        "title_en": "A Four-Week Plan for Beginners",
        "body_th": "สัปดาห์ ๑ — ๕ นาที/วัน เป้าหมายเดียวคือ “นั่งให้ครบทุกวัน”\nสัปดาห์ ๒ — ๑๐ นาที/วัน ฝึกนับลมหายใจ ๑ ถึง ๑๐\nสัปดาห์ ๓ — ๑๕ นาที/วัน เลิกนับ ดูลมเฉย ๆ เพิ่มระฆังกลางคาบ\nสัปดาห์ ๔ — ๒๐ นาที/วัน เพิ่มแผ่เมตตาท้ายคาบ ๒ นาที\n\nเคล็ดลับ: นั่งเวลาเดิม ที่เดิม ทุกวัน สมองจะสร้างนิสัยเร็วกว่าการใช้กำลังใจ",
        "body_en": "Week 1: 5 min/day. The only goal: sit every single day.\nWeek 2: 10 min/day. Practice counting breaths 1 to 10.\nWeek 3: 15 min/day. Drop the counting. Add an interval bell.\nWeek 4: 20 min/day. Add 2 minutes of metta at the end.\n\nTip: same time, same place, every day. Habit beats willpower.",
    },
]

# คำเตือนสติระหว่างนั่ง / gentle in-session reminders
REMINDERS = [
    {"th": "คลายไหล่ คลายกราม", "en": "Soften the shoulders and jaw."},
    {"th": "รู้ลมเข้า รู้ลมออก", "en": "Know the in-breath. Know the out-breath."},
    {"th": "เผลอแล้วกลับมา คือการภาวนา", "en": "Wandering, then returning. That is the practice."},
    {"th": "ไม่ต้องบังคับลมหายใจ", "en": "No need to control the breath."},
    {"th": "ปัจจุบันขณะ มีเพียงลมนี้", "en": "In this moment, only this breath."},
]

# ─────────────────────────────────────────────────────────────
#  ระบบเกม: ระดับ + เหรียญตรา / Levels & badges
# ─────────────────────────────────────────────────────────────
LEVEL_TITLES = [
    ("ผู้เริ่มต้น", "Beginner"),
    ("ผู้ตั้งใจ", "Seeker"),
    ("ผู้ฝึกหัด", "Apprentice"),
    ("ผู้มีสติ", "Mindful One"),
    ("ผู้สงบ", "Calm One"),
    ("ผู้ตั้งมั่น", "Steady One"),
    ("ผู้รู้ลม", "Breath Knower"),
    ("ผู้ปล่อยวาง", "Letting Go"),
    ("ผู้เบิกบาน", "Radiant"),
    ("ผู้ตื่นรู้", "Awakened"),
]

BADGES = [
    {"id": "first",    "icon": "🌱", "th": "ก้าวแรก",        "en": "First Step",    "desc_th": "นั่งสมาธิครั้งแรก",      "desc_en": "Complete your first sit"},
    {"id": "sit10",    "icon": "🪴", "th": "สิบครั้งแล้ว",    "en": "Ten Sits",      "desc_th": "นั่งครบ 10 ครั้ง",        "desc_en": "10 sessions logged"},
    {"id": "sit50",    "icon": "🌳", "th": "ห้าสิบครั้ง",     "en": "Fifty Sits",    "desc_th": "นั่งครบ 50 ครั้ง",        "desc_en": "50 sessions logged"},
    {"id": "sit100",   "icon": "🏔️", "th": "ร้อยครั้ง",       "en": "Hundred Sits",  "desc_th": "นั่งครบ 100 ครั้ง",       "desc_en": "100 sessions logged"},
    {"id": "min60",    "icon": "⏳", "th": "หนึ่งชั่วโมง",    "en": "One Hour",      "desc_th": "สะสมครบ 60 นาที",         "desc_en": "60 minutes accumulated"},
    {"id": "min600",   "icon": "🕰️", "th": "สิบชั่วโมง",      "en": "Ten Hours",     "desc_th": "สะสมครบ 600 นาที",        "desc_en": "600 minutes accumulated"},
    {"id": "min3000",  "icon": "💎", "th": "ห้าสิบชั่วโมง",   "en": "Fifty Hours",   "desc_th": "สะสมครบ 3,000 นาที",      "desc_en": "3,000 minutes accumulated"},
    {"id": "streak3",  "icon": "🔥", "th": "ไฟติดแล้ว",       "en": "Kindled",       "desc_th": "นั่งต่อเนื่อง 3 วัน",      "desc_en": "3-day streak"},
    {"id": "streak7",  "icon": "🎋", "th": "หนึ่งสัปดาห์",    "en": "One Week",      "desc_th": "นั่งต่อเนื่อง 7 วัน",      "desc_en": "7-day streak"},
    {"id": "streak30", "icon": "☀️", "th": "หนึ่งเดือนเต็ม",  "en": "Full Moon",     "desc_th": "นั่งต่อเนื่อง 30 วัน",     "desc_en": "30-day streak"},
    {"id": "early",    "icon": "🌅", "th": "อรุณรุ่ง",        "en": "Early Bird",    "desc_th": "นั่งก่อน 7 โมงเช้า",       "desc_en": "Sit before 7 a.m."},
    {"id": "night",    "icon": "🌙", "th": "ราตรีสงบ",        "en": "Night Owl",     "desc_th": "นั่งหลัง 3 ทุ่ม",          "desc_en": "Sit after 9 p.m."},
    {"id": "long30",   "icon": "🧘", "th": "สามสิบนาทีรวด",   "en": "Half Hour Sit", "desc_th": "นั่งครั้งเดียว 30 นาที",   "desc_en": "A single 30-minute sit"},
    {"id": "long60",   "icon": "🗿", "th": "หนึ่งชั่วโมงรวด", "en": "Hour Sit",      "desc_th": "นั่งครั้งเดียว 60 นาที",   "desc_en": "A single 60-minute sit"},
    {"id": "twice",    "icon": "☯️", "th": "เช้า-เย็น",       "en": "Twice a Day",   "desc_th": "นั่ง 2 ครั้งในวันเดียว",   "desc_en": "Two sits in one day"},
    {"id": "journal",  "icon": "📖", "th": "นักบันทึก",       "en": "Journaler",     "desc_th": "เขียนบันทึก 10 ครั้ง",     "desc_en": "Write 10 journal notes"},
]


# ─────────────────────────────────────────────────────────────
#  หน้าเว็บ (HTML + Tailwind CDN) — ส่วนที่ 1: หัวเอกสาร & หน้านั่งสมาธิ
# ─────────────────────────────────────────────────────────────
HTML_HEAD = r"""<!DOCTYPE html>
<html lang="th" class="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0b1020">
<title>สมาธิ · Sati — Meditation Timer</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🪷</text></svg>">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+Thai:wght@300;400;500;600;700&family=Noto+Serif+Thai:wght@400;500;600&family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
<script src="https://cdn.tailwindcss.com"></script>
<script>
tailwind.config = {
  darkMode: 'class',
  theme: { extend: {
    fontFamily: {
      sans: ['Noto Sans Thai','Inter','system-ui','sans-serif'],
      serif: ['Noto Serif Thai','Georgia','serif'],
      mono: ['ui-monospace','SFMono-Regular','monospace']
    }
  }}
}
</script>
<style>
  :root{ --a:#10b981; --a2:#6ee7b7; --a-dim:rgba(16,185,129,.16); }
  html{ -webkit-tap-highlight-color: transparent; }
  body{ font-family:'Noto Sans Thai','Inter',system-ui,sans-serif; }
  .font-dhamma{ font-family:'Noto Serif Thai',Georgia,serif; }

  /* พื้นหลัง */
  .bg-app{
    background:
      radial-gradient(1200px 600px at 10% -10%, rgba(16,185,129,.10), transparent 60%),
      radial-gradient(900px 500px at 110% 10%, rgba(99,102,241,.10), transparent 60%),
      #f6f7f5;
  }
  .dark .bg-app{
    background:
      radial-gradient(1200px 600px at 10% -10%, var(--a-dim), transparent 60%),
      radial-gradient(900px 500px at 110% 10%, rgba(99,102,241,.14), transparent 60%),
      #0b1020;
  }
  .card{ background:rgba(255,255,255,.72); border:1px solid rgba(15,23,42,.07);
         backdrop-filter:blur(14px); box-shadow:0 10px 30px -18px rgba(15,23,42,.35); }
  .dark .card{ background:rgba(255,255,255,.045); border-color:rgba(255,255,255,.09);
         box-shadow:0 18px 50px -28px rgba(0,0,0,.9); }

  .accent{ color:var(--a); }
  .bg-accent{ background:var(--a); }
  .ring-accent{ box-shadow:0 0 0 2px var(--a); }
  .btn-accent{ background:linear-gradient(140deg,var(--a),var(--a2)); color:#04140d;
               box-shadow:0 14px 34px -14px var(--a); }
  .btn-accent:active{ transform:scale(.975); }
  .chip{ transition:all .18s ease; }
  .chip-on{ background:var(--a); color:#04140d; border-color:transparent; font-weight:600; }

  input[type=range]{ -webkit-appearance:none; appearance:none; height:6px; border-radius:99px;
    background:rgba(127,140,141,.28); outline:none; }
  input[type=range]::-webkit-slider-thumb{ -webkit-appearance:none; width:20px; height:20px;
    border-radius:50%; background:var(--a); cursor:pointer; box-shadow:0 0 0 5px var(--a-dim); }
  input[type=range]::-moz-range-thumb{ width:20px;height:20px;border:0;border-radius:50%;
    background:var(--a); cursor:pointer; }

  .num, .field{ background:rgba(127,140,141,.10); border:1px solid rgba(127,140,141,.22); }
  .dark .num, .dark .field{ background:rgba(255,255,255,.05); border-color:rgba(255,255,255,.10); }
  .field:focus{ outline:none; border-color:var(--a); }

  @keyframes fadeUp{ from{opacity:0; transform:translateY(10px)} to{opacity:1; transform:none} }
  .fade-up{ animation:fadeUp .45s cubic-bezier(.22,.8,.3,1) both; }
  @keyframes soft{ from{opacity:0} to{opacity:1} }
  .soft-in{ animation:soft .7s ease both; }
  @keyframes pulseGlow{ 0%,100%{opacity:.35; transform:scale(1)} 50%{opacity:.75; transform:scale(1.06)} }
  .glow{ animation:pulseGlow 6s ease-in-out infinite; }
  @keyframes breathe{
    0%{ transform:scale(.62); }
    45%{ transform:scale(1); }
    55%{ transform:scale(1); }
    100%{ transform:scale(.62); }
  }
  .breath-ball{ animation:breathe var(--bd,10s) ease-in-out infinite; }
  @keyframes ripple{ from{ transform:scale(.7); opacity:.55 } to{ transform:scale(2.1); opacity:0 } }
  .ripple{ animation:ripple 2.6s ease-out infinite; }
  .ring-prog{ transition:stroke-dashoffset .35s linear; }
  .med-ring{ width:min(80vw, 46vh); height:min(80vw, 46vh); }
  .med-orb { width:min(72vw, 41vh); height:min(72vw, 41vh); }
  .time-big{ font-size:clamp(2.4rem, 10vh, 4.4rem); line-height:1.05; }

  ::-webkit-scrollbar{ width:9px; height:9px }
  ::-webkit-scrollbar-thumb{ background:rgba(127,140,141,.35); border-radius:99px }
  .no-sel{ user-select:none; }
  .tabnum{ font-variant-numeric: tabular-nums; }
</style>
</head>
<body class="bg-app text-slate-800 dark:text-slate-100 min-h-screen antialiased">

<!-- ═══════════ แถบบน / Header ═══════════ -->
<header class="sticky top-0 z-30 backdrop-blur-xl bg-white/60 dark:bg-[#0b1020]/70 border-b border-black/5 dark:border-white/10">
  <div class="max-w-5xl mx-auto px-4 h-16 flex items-center gap-3">
    <div class="w-10 h-10 rounded-2xl grid place-items-center text-xl btn-accent shrink-0">🪷</div>
    <div class="mr-auto leading-tight">
      <div class="font-semibold tracking-tight">สมาธิ · Sati</div>
      <div class="text-[11px] opacity-60" data-i18n="tagline">ตั้งเวลา · ระฆัง · บันทึกการภาวนา</div>
    </div>
    <div id="hdrStreak" class="hidden sm:flex items-center gap-1.5 px-3 h-9 rounded-full card text-sm">
      <span>🔥</span><span id="hdrStreakN" class="font-semibold tabnum">0</span>
      <span class="opacity-60 text-xs" data-i18n="days">วัน</span>
    </div>
    <div id="hdrLevel" class="hidden sm:flex items-center gap-1.5 px-3 h-9 rounded-full card text-sm">
      <span>⭐</span><span class="opacity-60 text-xs" data-i18n="lv">Lv.</span>
      <span id="hdrLevelN" class="font-semibold tabnum">1</span>
    </div>
    <button id="btnLang" class="h-9 px-3 rounded-full card text-xs font-semibold">TH / EN</button>
    <button id="btnTheme" class="h-9 w-9 rounded-full card grid place-items-center">🌙</button>
  </div>

  <!-- แท็บ / Tabs -->
  <div class="max-w-5xl mx-auto px-2 pb-2 overflow-x-auto">
    <div class="flex gap-1 min-w-max" id="tabs">
      <button data-tab="sit"      class="tab px-4 py-2 rounded-xl text-sm font-medium">🧘 <span data-i18n="tab_sit">นั่งสมาธิ</span></button>
      <button data-tab="log"      class="tab px-4 py-2 rounded-xl text-sm font-medium">📓 <span data-i18n="tab_log">บันทึก</span></button>
      <button data-tab="progress" class="tab px-4 py-2 rounded-xl text-sm font-medium">📈 <span data-i18n="tab_progress">ความก้าวหน้า</span></button>
      <button data-tab="learn"    class="tab px-4 py-2 rounded-xl text-sm font-medium">📖 <span data-i18n="tab_learn">เรียนรู้</span></button>
      <button data-tab="settings" class="tab px-4 py-2 rounded-xl text-sm font-medium">⚙️ <span data-i18n="tab_settings">ตั้งค่า</span></button>
    </div>
  </div>
</header>

<main class="max-w-5xl mx-auto px-4 py-6 pb-24">

<!-- ═══════════ หน้า: นั่งสมาธิ ═══════════ -->
<section id="view-sit" class="view space-y-5">

  <!-- การ์ดทักทาย + เป้าหมายวันนี้ -->
  <div class="card rounded-3xl p-5 sm:p-6 flex items-center gap-5 fade-up">
    <div class="relative w-[92px] h-[92px] shrink-0">
      <svg viewBox="0 0 100 100" class="w-full h-full -rotate-90">
        <circle cx="50" cy="50" r="42" fill="none" stroke="currentColor" class="opacity-10" stroke-width="9"/>
        <circle id="goalRing" cx="50" cy="50" r="42" fill="none" stroke="var(--a)" stroke-width="9"
                stroke-linecap="round" stroke-dasharray="263.9" stroke-dashoffset="263.9" class="ring-prog"/>
      </svg>
      <div class="absolute inset-0 grid place-items-center text-center leading-none">
        <div><div id="goalPct" class="text-lg font-bold tabnum">0%</div>
        <div class="text-[10px] opacity-55" data-i18n="today">วันนี้</div></div>
      </div>
    </div>
    <div class="min-w-0">
      <div id="greeting" class="text-lg sm:text-xl font-semibold font-dhamma">สวัสดี</div>
      <div id="goalText" class="text-sm opacity-65 mt-1">0 / 20 นาที</div>
      <div id="motto" class="text-xs opacity-50 mt-2 italic"></div>
    </div>
  </div>

  <!-- ตั้งเวลา -->
  <div class="card rounded-3xl p-5 sm:p-7 fade-up">
    <div class="flex items-baseline justify-between mb-4">
      <h2 class="font-semibold" data-i18n="set_time">ตั้งเวลา</h2>
      <label class="flex items-center gap-2 text-xs opacity-70 cursor-pointer">
        <input type="checkbox" id="openEnded" class="accent-emerald-500">
        <span data-i18n="open_ended">ไม่จำกัดเวลา</span>
      </label>
    </div>

    <div class="text-center select-none">
      <div class="inline-flex items-baseline gap-2">
        <span id="durBig" class="text-7xl sm:text-8xl font-light tabnum tracking-tight">15</span>
        <span class="text-xl opacity-55" data-i18n="min">นาที</span>
      </div>
    </div>

    <input id="durRange" type="range" min="1" max="120" value="15" class="w-full mt-5">

    <div id="presets" class="flex flex-wrap gap-2 justify-center mt-4"></div>

    <!-- ตัวเลือกด่วน -->
    <div class="grid sm:grid-cols-3 gap-3 mt-6">
      <div class="num rounded-2xl p-3">
        <div class="text-[11px] opacity-60 mb-1" data-i18n="prep">เตรียมตัวก่อนเริ่ม</div>
        <div class="flex items-center gap-2">
          <input id="prepSeconds" type="number" min="0" max="120" step="5" class="field w-full rounded-lg px-2 py-1.5 text-sm tabnum">
          <span class="text-xs opacity-60" data-i18n="sec">วิ</span>
        </div>
      </div>
      <div class="num rounded-2xl p-3">
        <div class="text-[11px] opacity-60 mb-1" data-i18n="interval">ระฆังเตือนทุก ๆ</div>
        <div class="flex items-center gap-2">
          <input id="intervalBell" type="number" min="0" max="60" step="1" class="field w-full rounded-lg px-2 py-1.5 text-sm tabnum">
          <span class="text-xs opacity-60" data-i18n="min">นาที</span>
        </div>
      </div>
      <div class="num rounded-2xl p-3">
        <div class="text-[11px] opacity-60 mb-1" data-i18n="closing">ช่วงแผ่เมตตาท้ายคาบ</div>
        <div class="flex items-center gap-2">
          <input id="closingSeconds" type="number" min="0" max="600" step="30" class="field w-full rounded-lg px-2 py-1.5 text-sm tabnum">
          <span class="text-xs opacity-60" data-i18n="sec">วิ</span>
        </div>
      </div>
    </div>

    <!-- คำกล่าวนำ -->
    <div class="num rounded-2xl p-3 mt-3 flex flex-col sm:flex-row sm:items-center gap-3">
      <label class="flex items-center gap-2 text-sm cursor-pointer shrink-0">
        <input type="checkbox" id="showOpening" class="accent-emerald-500">
        <span data-i18n="opening_words">คำกล่าวนำ</span>
      </label>
      <select id="openingId" class="field rounded-lg px-3 py-2 text-sm w-full sm:ml-auto sm:w-64"></select>
    </div>

    <button id="btnStart" class="btn-accent w-full mt-6 h-16 rounded-2xl text-lg font-bold tracking-wide">
      <span data-i18n="begin">เริ่มนั่งสมาธิ</span>
    </button>
    <div class="text-center text-[11px] opacity-45 mt-3" data-i18n="hint_sound">
      แตะเพื่อเริ่ม ระบบจะเปิดเสียงระฆังให้อัตโนมัติ
    </div>
  </div>

  <!-- สถิติย่อ -->
  <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 fade-up">
    <div class="card rounded-2xl p-4"><div class="text-2xl font-bold tabnum" id="sTotalSessions">0</div>
      <div class="text-[11px] opacity-60 mt-0.5" data-i18n="st_sessions">ครั้งทั้งหมด</div></div>
    <div class="card rounded-2xl p-4"><div class="text-2xl font-bold tabnum" id="sTotalTime">0</div>
      <div class="text-[11px] opacity-60 mt-0.5" data-i18n="st_time">เวลารวม</div></div>
    <div class="card rounded-2xl p-4"><div class="text-2xl font-bold tabnum" id="sStreak">0</div>
      <div class="text-[11px] opacity-60 mt-0.5" data-i18n="st_streak">ต่อเนื่อง (วัน)</div></div>
    <div class="card rounded-2xl p-4"><div class="text-2xl font-bold tabnum" id="sWeek">0</div>
      <div class="text-[11px] opacity-60 mt-0.5" data-i18n="st_week">สัปดาห์นี้ (นาที)</div></div>
  </div>
</section>
"""


# ─────────────────────────────────────────────────────────────
#  หน้าเว็บ — ส่วนที่ 2: บันทึก / ความก้าวหน้า / เรียนรู้ / ตั้งค่า / หน้าจอภาวนา
# ─────────────────────────────────────────────────────────────
HTML_BODY = r"""
<!-- ═══════════ หน้า: บันทึก ═══════════ -->
<section id="view-log" class="view hidden space-y-5">
  <div class="card rounded-3xl p-5 sm:p-6 fade-up">
    <div class="flex items-center justify-between mb-4">
      <h2 class="font-semibold" data-i18n="last14">14 วันที่ผ่านมา</h2>
      <div class="text-xs opacity-60"><span data-i18n="unit_min">นาที</span></div>
    </div>
    <div id="barChart" class="flex items-end gap-1.5 h-36"></div>
  </div>

  <div class="card rounded-3xl p-5 sm:p-6 fade-up">
    <div class="flex flex-wrap items-center gap-2 mb-4">
      <h2 class="font-semibold mr-auto" data-i18n="history">ประวัติการนั่ง</h2>
      <button id="btnExportCsv" class="text-xs px-3 py-1.5 rounded-lg num">⬇ CSV</button>
      <button id="btnExportJson" class="text-xs px-3 py-1.5 rounded-lg num">⬇ JSON</button>
    </div>
    <div id="logList" class="space-y-2"></div>
    <button id="btnMoreLog" class="hidden w-full mt-4 py-2.5 rounded-xl num text-sm" data-i18n="load_more">ดูเพิ่มเติม</button>
  </div>
</section>

<!-- ═══════════ หน้า: ความก้าวหน้า ═══════════ -->
<section id="view-progress" class="view hidden space-y-5">
  <!-- ระดับ -->
  <div class="card rounded-3xl p-5 sm:p-7 fade-up relative overflow-hidden">
    <div class="absolute -right-12 -top-12 w-56 h-56 rounded-full glow" style="background:radial-gradient(circle,var(--a) 0%,transparent 70%);opacity:.35"></div>
    <div class="relative flex items-center gap-4">
      <div class="w-16 h-16 rounded-2xl btn-accent grid place-items-center text-2xl font-bold tabnum" id="lvBadge">1</div>
      <div class="min-w-0">
        <div class="text-xs opacity-60" data-i18n="your_level">ระดับของคุณ</div>
        <div id="lvTitle" class="text-xl font-semibold font-dhamma">ผู้เริ่มต้น</div>
      </div>
      <div class="ml-auto text-right">
        <div class="text-2xl font-bold tabnum" id="xpNow">0</div>
        <div class="text-[11px] opacity-55">XP</div>
      </div>
    </div>
    <div class="relative mt-5">
      <div class="h-2.5 rounded-full bg-black/10 dark:bg-white/10 overflow-hidden">
        <div id="xpBar" class="h-full rounded-full btn-accent transition-all duration-700" style="width:0%"></div>
      </div>
      <div class="flex justify-between text-[11px] opacity-55 mt-1.5">
        <span id="xpLabel">0 / 100 XP</span>
        <span id="xpNext"></span>
      </div>
    </div>
  </div>

  <!-- สถิติ -->
  <div id="statGrid" class="grid grid-cols-2 sm:grid-cols-3 gap-3 fade-up"></div>

  <!-- ปฏิทินความสม่ำเสมอ -->
  <div class="card rounded-3xl p-5 sm:p-6 fade-up">
    <h2 class="font-semibold mb-4" data-i18n="heatmap">ปฏิทินการภาวนา</h2>
    <div class="overflow-x-auto pb-1">
      <div id="heatmap" class="inline-grid grid-flow-col gap-[3px]" style="grid-template-rows:repeat(7,minmax(0,1fr))"></div>
    </div>
    <div class="flex items-center gap-1.5 text-[11px] opacity-55 mt-3">
      <span data-i18n="less">น้อย</span>
      <i class="w-3 h-3 rounded-[3px] bg-black/10 dark:bg-white/10"></i>
      <i class="w-3 h-3 rounded-[3px]" style="background:var(--a);opacity:.3"></i>
      <i class="w-3 h-3 rounded-[3px]" style="background:var(--a);opacity:.55"></i>
      <i class="w-3 h-3 rounded-[3px]" style="background:var(--a);opacity:.78"></i>
      <i class="w-3 h-3 rounded-[3px]" style="background:var(--a)"></i>
      <span data-i18n="more">มาก</span>
    </div>
  </div>

  <!-- เหรียญตรา -->
  <div class="card rounded-3xl p-5 sm:p-6 fade-up">
    <div class="flex items-center justify-between mb-4">
      <h2 class="font-semibold" data-i18n="badges">เหรียญตรา</h2>
      <span id="badgeCount" class="text-xs opacity-60 tabnum">0/16</span>
    </div>
    <div id="badgeGrid" class="grid grid-cols-2 sm:grid-cols-4 gap-3"></div>
  </div>
</section>

<!-- ═══════════ หน้า: เรียนรู้ ═══════════ -->
<section id="view-learn" class="view hidden space-y-4">
  <div class="card rounded-3xl p-6 sm:p-8 fade-up text-center">
    <div class="text-4xl mb-3">🪷</div>
    <h2 class="text-xl font-semibold font-dhamma" data-i18n="learn_title">อานาปานสติเบื้องต้น</h2>
    <p class="text-sm opacity-65 mt-2 max-w-xl mx-auto" data-i18n="learn_sub">
      แนวทางการเจริญสติกำหนดลมหายใจเข้า-ออก ตามหลักพระพุทธศาสนา สำหรับผู้เริ่มต้น
    </p>
  </div>
  <div id="lessonList" class="space-y-3"></div>
  <div class="card rounded-3xl p-5 sm:p-6 fade-up">
    <h3 class="font-semibold mb-3" data-i18n="openings_title">บทคำกล่าวนำทั้งหมด</h3>
    <div id="openingList" class="space-y-3"></div>
  </div>
</section>

<!-- ═══════════ หน้า: ตั้งค่า ═══════════ -->
<section id="view-settings" class="view hidden space-y-4">
  <div id="settingsRoot" class="space-y-4"></div>

  <!-- คำกล่าว/คำชม ของฉัน -->
  <div class="card rounded-3xl p-5 sm:p-6">
    <h3 class="font-semibold mb-1" data-i18n="my_content">บทของฉัน</h3>
    <p class="text-xs opacity-60 mb-4" data-i18n="my_content_sub">เพิ่มคำกล่าวนำ หรือคำให้กำลังใจในแบบของคุณเอง</p>
    <div class="flex gap-2 mb-3">
      <select id="ccKind" class="field rounded-lg px-3 py-2 text-sm">
        <option value="opening" data-i18n="kind_opening">คำกล่าวนำ</option>
        <option value="praise" data-i18n="kind_praise">คำชม</option>
      </select>
      <input id="ccTitle" class="field rounded-lg px-3 py-2 text-sm flex-1" placeholder="ชื่อบท / Title">
    </div>
    <textarea id="ccBody" rows="3" class="field rounded-lg px-3 py-2 text-sm w-full" placeholder="เนื้อความ / Text"></textarea>
    <button id="btnAddCC" class="btn-accent mt-3 px-4 py-2 rounded-xl text-sm font-semibold" data-i18n="add">เพิ่ม</button>
    <div id="ccList" class="mt-4 space-y-2"></div>
  </div>

  <!-- ข้อมูล -->
  <div class="card rounded-3xl p-5 sm:p-6">
    <h3 class="font-semibold mb-4" data-i18n="data">ข้อมูล</h3>
    <div class="flex flex-wrap gap-2">
      <button id="btnTestBell" class="px-4 py-2 rounded-xl num text-sm">🔔 <span data-i18n="test_bell">ทดสอบเสียงระฆัง</span></button>
      <button id="btnResetSettings" class="px-4 py-2 rounded-xl num text-sm" data-i18n="reset_settings">คืนค่าตั้งต้น</button>
      <button id="btnWipe" class="px-4 py-2 rounded-xl text-sm border border-rose-500/40 text-rose-500" data-i18n="wipe">ลบข้อมูลทั้งหมด</button>
    </div>
  </div>
</section>

</main>

<!-- ═══════════ โมดัล: คำกล่าวนำ ═══════════ -->
<div id="ovOpening" class="fixed inset-0 z-50 hidden items-center justify-center p-4 bg-black/70 backdrop-blur-md">
  <div class="card rounded-3xl p-6 sm:p-8 max-w-lg w-full fade-up max-h-[90vh] overflow-y-auto">
    <div class="text-center text-3xl mb-3">🙏</div>
    <h3 id="opTitle" class="text-center text-lg font-semibold font-dhamma mb-4"></h3>
    <p id="opBody" class="text-center whitespace-pre-line leading-relaxed font-dhamma opacity-90"></p>

    <div id="moodBeforeWrap" class="mt-6">
      <div class="text-xs opacity-60 text-center mb-2" data-i18n="mood_before">ตอนนี้ใจคุณเป็นอย่างไร</div>
      <div id="moodBefore" class="flex justify-center gap-2"></div>
    </div>

    <div class="flex gap-2 mt-7">
      <button id="opCancel" class="flex-1 py-3 rounded-xl num text-sm" data-i18n="cancel">ยกเลิก</button>
      <button id="opGo" class="flex-[2] py-3 rounded-xl btn-accent font-semibold" data-i18n="ready">พร้อมแล้ว เริ่มเลย</button>
    </div>
  </div>
</div>

<!-- ═══════════ หน้าจอภาวนา (เต็มจอ) ═══════════ -->
<div id="ovSession" class="fixed inset-0 z-50 hidden bg-[#070b16] text-slate-100 no-sel">
  <div class="absolute inset-0 overflow-hidden pointer-events-none">
    <div class="absolute -top-32 left-1/4 w-[34rem] h-[34rem] rounded-full glow" style="background:radial-gradient(circle,var(--a) 0%,transparent 70%);opacity:.22"></div>
    <div class="absolute -bottom-32 -right-24 w-[30rem] h-[30rem] rounded-full glow" style="background:radial-gradient(circle,#6366f1 0%,transparent 70%);opacity:.22;animation-delay:2s"></div>
  </div>

  <div class="relative h-full flex flex-col items-center justify-between py-5 sm:py-8 px-5 gap-3">
    <!-- บน -->
    <div class="w-full max-w-md flex items-center text-sm">
      <div id="sesPhase" class="px-3 py-1 rounded-full bg-white/10 text-xs tracking-wide"></div>
      <div id="sesClock" class="ml-auto text-xs opacity-50 tabnum"></div>
    </div>

    <!-- กลาง -->
    <div class="relative grid place-items-center min-h-0 shrink">
      <div id="breathGuide" class="absolute med-orb rounded-full breath-ball"
           style="background:radial-gradient(circle at 50% 45%, var(--a), transparent 70%); opacity:.22"></div>
      <div class="absolute med-orb rounded-full ripple border" style="border-color:var(--a);opacity:.25"></div>

      <svg viewBox="0 0 300 300" class="med-ring -rotate-90 relative">
        <circle cx="150" cy="150" r="136" fill="none" stroke="#ffffff" stroke-opacity=".08" stroke-width="5"/>
        <circle id="sesRing" cx="150" cy="150" r="136" fill="none" stroke="var(--a)" stroke-width="5"
                stroke-linecap="round" stroke-dasharray="854.5" stroke-dashoffset="854.5" class="ring-prog"/>
      </svg>

      <div class="absolute text-center">
        <div id="sesTime" class="time-big font-extralight tabnum tracking-tight">15:00</div>
        <div id="sesSub" class="text-xs opacity-45 mt-2 tabnum"></div>
        <div id="sesBreath" class="text-sm opacity-55 mt-3 h-5"></div>
      </div>
    </div>

    <!-- ล่าง -->
    <div class="w-full max-w-md">
      <div id="sesReminder" class="text-center text-sm opacity-0 transition-opacity duration-1000 font-dhamma mb-6 h-6"></div>
      <div class="flex items-center justify-center gap-3">
        <button id="sesAdd" class="h-12 px-4 rounded-2xl bg-white/10 text-sm">+1 <span data-i18n="min">นาที</span></button>
        <button id="sesPause" class="h-16 w-16 rounded-full btn-accent grid place-items-center text-2xl">⏸</button>
        <button id="sesStop" class="h-12 px-4 rounded-2xl bg-white/10 text-sm" data-i18n="finish">จบ</button>
      </div>
      <div class="text-center text-[11px] opacity-30 mt-4" data-i18n="stay_hint">วางเครื่องไว้ แล้วหลับตาลงเบา ๆ</div>
    </div>
  </div>
</div>

<!-- ═══════════ โมดัล: จบคาบ ═══════════ -->
<div id="ovFinish" class="fixed inset-0 z-50 hidden items-center justify-center p-4 bg-black/75 backdrop-blur-md overflow-y-auto">
  <div class="card rounded-3xl p-6 sm:p-8 max-w-lg w-full my-8 fade-up">
    <div class="text-center">
      <div class="text-5xl mb-3">🎉</div>
      <div id="fiDuration" class="text-3xl font-light tabnum"></div>
      <div class="text-xs opacity-55 mt-1" data-i18n="well_sat">การภาวนาเสร็จสมบูรณ์</div>
    </div>

    <div id="fiPraise" class="mt-5 rounded-2xl p-4 text-center font-dhamma leading-relaxed"
         style="background:var(--a-dim)"></div>

    <div id="fiXp" class="flex items-center justify-center gap-4 mt-5 text-sm"></div>
    <div id="fiBadges" class="mt-4 grid gap-2"></div>

    <div id="fiMoodWrap" class="mt-6">
      <div class="text-xs opacity-60 text-center mb-2" data-i18n="mood_after">หลังนั่งแล้วรู้สึกอย่างไร</div>
      <div id="moodAfter" class="flex justify-center gap-2"></div>
    </div>

    <div class="mt-5">
      <div class="text-xs opacity-60 text-center mb-2" data-i18n="rate">ให้คะแนนสมาธิครั้งนี้</div>
      <div id="rateStars" class="flex justify-center gap-1.5 text-3xl"></div>
    </div>

    <textarea id="fiNotes" rows="3" class="field rounded-xl px-3 py-2 text-sm w-full mt-5"
              placeholder="บันทึกสั้น ๆ… วันนี้ใจเป็นอย่างไร / A short note…"></textarea>

    <div class="flex gap-2 mt-5">
      <button id="fiSkip" class="flex-1 py-3 rounded-xl num text-sm" data-i18n="no_save">ไม่บันทึก</button>
      <button id="fiSave" class="flex-[2] py-3 rounded-xl btn-accent font-semibold" data-i18n="save_session">บันทึกผล</button>
    </div>
  </div>
</div>

<div id="toast" class="fixed bottom-6 left-1/2 -translate-x-1/2 z-[60] pointer-events-none space-y-2"></div>
"""


# ─────────────────────────────────────────────────────────────
#  หน้าเว็บ — ส่วนที่ 3: สคริปต์ (ตัวจับเวลา, เสียงระฆัง, สองภาษา, เกม)
# ─────────────────────────────────────────────────────────────
HTML_JS = r"""
<script>
/* ═══════════════ พื้นฐาน / Basics ═══════════════ */
const $  = (s, r=document) => r.querySelector(s);
const $$ = (s, r=document) => Array.from(r.querySelectorAll(s));
const clamp = (v,a,b) => Math.max(a, Math.min(b, v));
const pad = n => String(n).padStart(2,'0');

let S = {}, STATS = {}, CONTENT = {}, SESSIONS = [], LOG_LIMIT = 15;

const ACCENTS = {
  emerald:['#10b981','#6ee7b7'], jade:['#14b8a6','#5eead4'], gold:['#d4af37','#f2dd94'],
  amber:['#f59e0b','#fcd34d'],  lotus:['#f472b6','#fbcfe8'], sky:['#0ea5e9','#7dd3fc'],
  violet:['#8b5cf6','#c4b5fd'], saffron:['#ea8c00','#ffcf87']
};

/* ═══════════════ ข้อความสองภาษา / i18n ═══════════════ */
const TXT = {
  tagline:['ตั้งเวลา · ระฆัง · บันทึกการภาวนา','Timer · Bells · Practice journal'],
  days:['วัน','days'], lv:['ระดับ','Lv.'],
  tab_sit:['นั่งสมาธิ','Meditate'], tab_log:['บันทึก','Journal'],
  tab_progress:['ความก้าวหน้า','Progress'], tab_learn:['เรียนรู้','Learn'], tab_settings:['ตั้งค่า','Settings'],
  today:['วันนี้','Today'], set_time:['ตั้งเวลา','Set your time'],
  open_ended:['ไม่จำกัดเวลา','Open-ended'], min:['นาที','min'], sec:['วินาที','sec'],
  prep:['เตรียมตัวก่อนเริ่ม','Preparation'], interval:['ระฆังเตือนทุก ๆ','Interval bell every'],
  closing:['ช่วงแผ่เมตตาท้ายคาบ','Closing metta'], opening_words:['คำกล่าวนำ','Opening words'],
  begin:['เริ่มนั่งสมาธิ','Begin meditation'],
  hint_sound:['แตะเพื่อเริ่ม ระบบจะเปิดเสียงระฆังให้อัตโนมัติ','Tap to start — bell audio unlocks automatically'],
  st_sessions:['ครั้งทั้งหมด','Total sits'], st_time:['เวลารวม','Total time'],
  st_streak:['ต่อเนื่อง (วัน)','Streak (days)'], st_week:['สัปดาห์นี้ (นาที)','This week (min)'],
  last14:['14 วันที่ผ่านมา','Last 14 days'], unit_min:['นาที','minutes'],
  history:['ประวัติการนั่ง','Session history'], load_more:['ดูเพิ่มเติม','Load more'],
  your_level:['ระดับของคุณ','Your level'], heatmap:['ปฏิทินการภาวนา','Practice calendar'],
  less:['น้อย','less'], more:['มาก','more'], badges:['เหรียญตรา','Badges'],
  learn_title:['อานาปานสติเบื้องต้น','Anapanasati for Beginners'],
  learn_sub:['แนวทางการเจริญสติกำหนดลมหายใจเข้า-ออก ตามหลักพระพุทธศาสนา สำหรับผู้เริ่มต้น',
             'Mindfulness of breathing in the Buddhist tradition — a practical guide for beginners'],
  openings_title:['บทคำกล่าวนำทั้งหมด','All opening words'],
  my_content:['บทของฉัน','My own texts'],
  my_content_sub:['เพิ่มคำกล่าวนำ หรือคำให้กำลังใจในแบบของคุณเอง','Add your own opening words or words of encouragement'],
  kind_opening:['คำกล่าวนำ','Opening'], kind_praise:['คำชม','Encouragement'],
  add:['เพิ่ม','Add'], data:['ข้อมูล','Data'], test_bell:['ทดสอบเสียงระฆัง','Test bell'],
  reset_settings:['คืนค่าตั้งต้น','Reset settings'], wipe:['ลบข้อมูลทั้งหมด','Erase all data'],
  mood_before:['ตอนนี้ใจคุณเป็นอย่างไร','How is your mind right now?'],
  mood_after:['หลังนั่งแล้วรู้สึกอย่างไร','How do you feel now?'],
  cancel:['ยกเลิก','Cancel'], ready:['พร้อมแล้ว เริ่มเลย','I am ready — begin'],
  finish:['จบ','Finish'], stay_hint:['วางเครื่องไว้ แล้วหลับตาลงเบา ๆ','Set the device down and let the eyes close'],
  well_sat:['การภาวนาเสร็จสมบูรณ์','Your sitting is complete'],
  rate:['ให้คะแนนสมาธิครั้งนี้','Rate this sitting'],
  no_save:['ไม่บันทึก','Discard'], save_session:['บันทึกผล','Save session'],
  /* ใช้ใน JS */
  ph_prep:['เตรียมตัว','Settling in'], ph_sit:['ภาวนา','Meditating'],
  ph_closing:['แผ่เมตตา','Metta'], ph_pause:['หยุดชั่วคราว','Paused'],
  breath_in:['หายใจเข้า','Breathe in'], breath_out:['หายใจออก','Breathe out'],
  metta_text:['ขอให้ข้าพเจ้ามีความสุข · ขอให้สรรพสัตว์มีความสุข','May I be well · May all beings be well'],
  greet_morning:['อรุณสวัสดิ์','Good morning'], greet_day:['สวัสดีตอนกลางวัน','Good afternoon'],
  greet_evening:['สวัสดีตอนเย็น','Good evening'], greet_night:['ราตรีสวัสดิ์','Good evening'],
  goal_of:['จาก','of'], saved:['บันทึกแล้ว','Saved'], deleted:['ลบแล้ว','Deleted'],
  discarded:['ไม่ได้บันทึกคาบนี้','Session discarded'],
  settings_saved:['บันทึกการตั้งค่าแล้ว','Settings saved'],
  confirm_wipe:['ลบประวัติการนั่งทั้งหมด? ย้อนกลับไม่ได้','Erase all session history? This cannot be undone.'],
  confirm_del:['ลบบันทึกนี้?','Delete this entry?'],
  no_sessions:['ยังไม่มีบันทึก เริ่มนั่งครั้งแรกกันเลย 🌱','No sessions yet. Start your first sit 🌱'],
  xp_gained:['ได้รับ','Gained'], new_badge:['ได้รับเหรียญใหม่!','New badge unlocked!'],
  st_longest:['ต่อเนื่องสูงสุด','Longest streak'], st_avg:['เฉลี่ยต่อครั้ง','Avg per sit'],
  st_today:['วันนี้','Today'], st_month:['30 วันล่าสุด','Last 30 days'],
  st_rating:['คะแนนเฉลี่ย','Avg rating'], st_best:['วันที่นานที่สุด','Best day'],
  locked:['ยังไม่ปลดล็อก','Locked'],
  g_appearance:['รูปลักษณ์','Appearance'], g_time:['เวลา','Timing'], g_sound:['เสียง','Sound'],
  g_exp:['ประสบการณ์','Experience'], g_goal:['เป้าหมาย','Goals'],
  f_lang:['ภาษา','Language'], f_theme:['ธีม','Theme'], f_accent:['สีหลัก','Accent colour'],
  f_font:['ขนาดตัวอักษร','Font size'], f_duration:['ระยะเวลาเริ่มต้น (นาที)','Default duration (min)'],
  f_prep:['เวลาเตรียมตัว (วินาที)','Preparation (sec)'],
  f_interval:['ระฆังกลางคาบทุก ๆ (นาที, 0 = ปิด)','Interval bell every (min, 0 = off)'],
  f_closing:['ช่วงแผ่เมตตา (วินาที)','Closing metta (sec)'],
  f_countup:['นับเวลาขึ้นแทนนับถอยหลัง','Count up instead of down'],
  f_openended:['นั่งแบบไม่จำกัดเวลา','Open-ended sitting'],
  f_presets:['ปุ่มเวลาด่วน (คั่นด้วย ,)','Quick presets (comma separated)'],
  f_startbell:['เสียงระฆังเริ่ม','Starting bell'], f_endbell:['เสียงระฆังจบ','Ending bell'],
  f_intervalsound:['เสียงระฆังกลางคาบ','Interval bell'],
  f_startstrikes:['จำนวนครั้งที่ตี (เริ่ม)','Strikes at start'],
  f_endstrikes:['จำนวนครั้งที่ตี (จบ)','Strikes at end'],
  f_volume:['ระดับเสียงระฆัง','Bell volume'], f_ambience:['เสียงบรรยากาศ','Ambient sound'],
  f_ambvol:['ระดับเสียงบรรยากาศ','Ambient volume'],
  f_showopening:['แสดงคำกล่าวนำก่อนเริ่ม','Show opening words'],
  f_openingid:['บทที่ใช้','Which opening'], f_showpraise:['แสดงคำชมเมื่อจบ','Show encouragement at the end'],
  f_askmood:['ถามอารมณ์ก่อน/หลัง','Ask about mood'], f_showclock:['แสดงนาฬิกาขณะนั่ง','Show clock while sitting'],
  f_keepawake:['ไม่ให้หน้าจอดับ','Keep screen awake'],
  f_breathguide:['วงกลมนำลมหายใจ','Breathing guide circle'],
  f_breathin:['หายใจเข้า (วินาที)','Inhale (sec)'], f_breathout:['หายใจออก (วินาที)','Exhale (sec)'],
  f_dailygoal:['เป้าหมายต่อวัน (นาที)','Daily goal (min)'],
  f_weekdays:['เป้าหมายจำนวนวันต่อสัปดาห์','Target days per week'],
  random_pick:['สุ่มทุกครั้ง','Random each time'],
  bell_bowl:['ขันระฆัง','Singing bowl'], bell_chime:['กระดิ่ง','Chime'], bell_gong:['ฆ้อง','Gong'],
  bell_wood:['เกราะไม้','Wood block'], bell_none:['ไม่มีเสียง','Silent'],
  amb_none:['ไม่มี','None'], amb_rain:['สายฝน','Rain'], amb_ocean:['คลื่นทะเล','Ocean'],
  amb_forest:['ป่าไม้','Forest'], amb_hum:['เสียงโอม','Low drone'],
};
const LANGI = () => (S.lang === 'en' ? 1 : 0);
const t = k => (TXT[k] ? TXT[k][LANGI()] : k);
const L  = (o, f) => o[f + '_' + (S.lang === 'en' ? 'en' : 'th')] ?? o[S.lang === 'en' ? 'en' : 'th'] ?? '';

/* ═══════════════ เรียก API ═══════════════ */
async function api(url, method='GET', body=null){
  const opt = { method, headers:{'Content-Type':'application/json'} };
  if (body) opt.body = JSON.stringify(body);
  const r = await fetch(url, opt);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
function toast(msg, icon='✓'){
  const d = document.createElement('div');
  d.className = 'card rounded-2xl px-4 py-2.5 text-sm shadow-xl fade-up';
  d.textContent = icon + '  ' + msg;
  $('#toast').appendChild(d);
  setTimeout(()=>{ d.style.transition='opacity .4s'; d.style.opacity='0'; setTimeout(()=>d.remove(),400); }, 2600);
}

/* ═══════════════ เสียง / Web Audio ═══════════════ */
const Snd = {
  ctx:null, amb:null, ambGain:null,
  ensure(){
    if (!this.ctx) this.ctx = new (window.AudioContext || window.webkitAudioContext)();
    if (this.ctx.state === 'suspended') this.ctx.resume();
    return this.ctx;
  },
  strike(type, when=0, vol=1){
    if (type === 'none') return;
    const c = this.ensure(), t0 = c.currentTime + when;
    const master = c.createGain();
    master.gain.value = (S.volume ?? .7) * vol;
    master.connect(c.destination);

    const specs = {
      bowl:  { base:210, parts:[1,2.74,5.38,8.93,13.3], gains:[1,.5,.28,.14,.07], dur:8,   type:'sine' },
      chime: { base:932, parts:[1,2.01,3.02,4.6],       gains:[1,.45,.22,.1],     dur:3.4, type:'sine' },
      gong:  { base:96,  parts:[1,1.48,2.12,3.31,4.9,6.4], gains:[1,.7,.5,.32,.2,.12], dur:11, type:'sine' },
      wood:  { base:620, parts:[1,2.3],                 gains:[1,.4],             dur:.22, type:'triangle' },
    };
    const sp = specs[type] || specs.bowl;

    sp.parts.forEach((m,i)=>{
      const o = c.createOscillator(), g = c.createGain();
      o.type = sp.type;
      o.frequency.value = sp.base * m;
      const peak = sp.gains[i] * .42;
      g.gain.setValueAtTime(0, t0);
      g.gain.linearRampToValueAtTime(peak, t0 + 0.008);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + sp.dur * (1 - i*0.09));
      // สั่นเบา ๆ ให้เหมือนระฆังจริง
      if (type !== 'wood'){
        const lfo = c.createOscillator(), lg = c.createGain();
        lfo.frequency.value = 0.7 + i*0.9; lg.gain.value = sp.base*m*0.0022;
        lfo.connect(lg); lg.connect(o.frequency); lfo.start(t0); lfo.stop(t0+sp.dur);
      }
      o.connect(g); g.connect(master);
      o.start(t0); o.stop(t0 + sp.dur + .1);
    });

    // เสียงกระทบตอนตี
    const nb = c.createBuffer(1, c.sampleRate*0.08, c.sampleRate);
    const dt = nb.getChannelData(0);
    for (let i=0;i<dt.length;i++) dt[i] = (Math.random()*2-1) * Math.pow(1 - i/dt.length, 3);
    const ns = c.createBufferSource(), nf = c.createBiquadFilter(), ng = c.createGain();
    ns.buffer = nb; nf.type='bandpass'; nf.frequency.value = sp.base*4; ng.gain.value = .12;
    ns.connect(nf); nf.connect(ng); ng.connect(master);
    ns.start(t0);
  },
  bell(type, strikes=1){
    const gap = type === 'gong' ? 3.2 : type === 'wood' ? .35 : 2.4;
    for (let i=0;i<Math.max(1,strikes);i++) this.strike(type, i*gap);
  },
  startAmbience(){
    this.stopAmbience();
    const kind = S.ambience || 'none';
    if (kind === 'none') return;
    const c = this.ensure();
    const g = c.createGain(); g.gain.value = 0;
    g.connect(c.destination);
    g.gain.linearRampToValueAtTime(S.ambienceVolume ?? .25, c.currentTime + 3);
    this.ambGain = g;
    const nodes = [];

    if (kind === 'hum'){
      [72, 108, 144].forEach((f,i)=>{
        const o = c.createOscillator(), og = c.createGain();
        o.type='sine'; o.frequency.value=f; og.gain.value = .3/(i+1);
        o.connect(og); og.connect(g); o.start(); nodes.push(o);
      });
    } else {
      const len = c.sampleRate * 4;
      const buf = c.createBuffer(1, len, c.sampleRate);
      const d = buf.getChannelData(0);
      let last = 0;
      for (let i=0;i<len;i++){ const w = Math.random()*2-1; last = (last + 0.02*w)/1.02; d[i] = last*3.2; }
      const src = c.createBufferSource(); src.buffer = buf; src.loop = true;
      const f = c.createBiquadFilter();
      if (kind === 'rain'){ f.type='highpass'; f.frequency.value=900; }
      else if (kind === 'ocean'){ f.type='lowpass'; f.frequency.value=520; }
      else { f.type='bandpass'; f.frequency.value=1500; f.Q.value=.6; }
      const swell = c.createGain(); swell.gain.value = .7;
      if (kind === 'ocean' || kind === 'forest'){
        const lfo = c.createOscillator(), lg = c.createGain();
        lfo.frequency.value = kind==='ocean' ? 0.08 : 0.05; lg.gain.value = .45;
        lfo.connect(lg); lg.connect(swell.gain); lfo.start(); nodes.push(lfo);
      }
      src.connect(f); f.connect(swell); swell.connect(g); src.start(); nodes.push(src);
    }
    this.amb = nodes;
  },
  stopAmbience(){
    if (this.ambGain){
      try{ this.ambGain.gain.linearRampToValueAtTime(0, this.ctx.currentTime + 1.2); }catch(e){}
      const g = this.ambGain, n = this.amb || [];
      setTimeout(()=>{ n.forEach(x=>{ try{x.stop()}catch(e){} }); try{g.disconnect()}catch(e){} }, 1400);
    }
    this.amb = null; this.ambGain = null;
  }
};

/* ═══════════════ รูปแบบเวลา ═══════════════ */
function mmss(sec){
  sec = Math.max(0, Math.round(sec));
  const h = Math.floor(sec/3600), m = Math.floor(sec%3600/60), s = sec%60;
  return h ? h + ':' + pad(m) + ':' + pad(s) : pad(m) + ':' + pad(s);
}
function humanMin(minutes){
  const m = Math.round(minutes);
  if (m < 60) return m + ' ' + t('min');
  const h = Math.floor(m/60), r = m%60;
  return S.lang==='en' ? (h + 'h ' + (r?r+'m':'')).trim() : (h + ' ชม.' + (r? ' ' + r + ' น.' : ''));
}
function dstr(d){ return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate()); }
</script>
"""


# ─────────────────────────────────────────────────────────────
#  หน้าเว็บ — ส่วนที่ 4: การแสดงผล, ตัวจับเวลา, การตั้งค่า
# ─────────────────────────────────────────────────────────────
HTML_JS2 = r"""
<script>
/* ═══════════════ ใช้ค่าตั้งค่ากับหน้าเว็บ ═══════════════ */
function applyTheme(){
  document.documentElement.classList.toggle('dark', S.theme !== 'light');
  $('#btnTheme').textContent = S.theme === 'light' ? '☀️' : '🌙';
  const a = ACCENTS[S.accent] || ACCENTS.emerald;
  document.documentElement.style.setProperty('--a', a[0]);
  document.documentElement.style.setProperty('--a2', a[1]);
  document.documentElement.style.setProperty('--a-dim', a[0] + '28');
  document.documentElement.style.fontSize = (16 * (S.fontScale || 1)) + 'px';
  document.documentElement.lang = S.lang;
}
function applyI18n(){
  $$('[data-i18n]').forEach(el => { const k = el.dataset.i18n; if (TXT[k]) el.textContent = t(k); });
  $('#btnLang').textContent = S.lang === 'en' ? 'EN → ไทย' : 'ไทย → EN';
}

/* ═══════════════ แท็บ ═══════════════ */
function showTab(name){
  $$('.view').forEach(v => v.classList.add('hidden'));
  $('#view-' + name).classList.remove('hidden');
  $$('.tab').forEach(b => {
    const on = b.dataset.tab === name;
    b.classList.toggle('chip-on', on);
    b.classList.toggle('opacity-55', !on);
  });
  localStorage.setItem('satiTab', name);
  window.scrollTo({top:0, behavior:'smooth'});
}

/* ═══════════════ หน้านั่งสมาธิ ═══════════════ */
function renderSit(){
  const h = new Date().getHours();
  const g = h < 11 ? 'greet_morning' : h < 16 ? 'greet_day' : h < 20 ? 'greet_evening' : 'greet_night';
  $('#greeting').textContent = t(g);

  const todayMin = STATS.today_minutes || 0, goal = S.dailyGoal || 20;
  const pct = clamp(goal ? todayMin/goal : 0, 0, 1);
  $('#goalRing').style.strokeDashoffset = (263.9 * (1 - pct)).toFixed(1);
  $('#goalPct').textContent = Math.round(pct*100) + '%';
  $('#goalText').textContent = Math.round(todayMin) + ' / ' + goal + ' ' + t('min');
  const rem = CONTENT.reminders || [];
  if (rem.length) $('#motto').textContent = '“' + L(rem[Math.floor(Math.random()*rem.length)]) + '”';

  $('#durBig').textContent = S.openEnded ? '∞' : S.duration;
  $('#durRange').value = S.duration;
  $('#durRange').disabled = !!S.openEnded;
  $('#durRange').style.opacity = S.openEnded ? .35 : 1;
  $('#openEnded').checked = !!S.openEnded;
  $('#prepSeconds').value = S.prepSeconds;
  $('#intervalBell').value = S.intervalBell;
  $('#closingSeconds').value = S.closingSeconds;
  $('#showOpening').checked = !!S.showOpening;

  // ปุ่มเวลาด่วน
  const wrap = $('#presets'); wrap.innerHTML = '';
  (S.presets || []).forEach(p => {
    const b = document.createElement('button');
    b.className = 'chip px-4 py-2 rounded-xl text-sm num ' + (!S.openEnded && +p === +S.duration ? 'chip-on' : '');
    b.textContent = p;
    b.onclick = () => { S.openEnded = false; setDuration(+p); };
    wrap.appendChild(b);
  });

  // ตัวเลือกคำกล่าวนำ
  const sel = $('#openingId'); sel.innerHTML = '';
  const optR = new Option(t('random_pick'), 'random'); sel.add(optR);
  allOpenings().forEach(o => sel.add(new Option(L(o,'title'), o.id)));
  sel.value = S.openingId || 'random';

  $('#sTotalSessions').textContent = STATS.total_sessions || 0;
  $('#sTotalTime').textContent = humanMin(STATS.total_minutes || 0);
  $('#sStreak').textContent = STATS.streak || 0;
  $('#sWeek').textContent = Math.round(STATS.week_minutes || 0);
  $('#hdrStreakN').textContent = STATS.streak || 0;
  $('#hdrLevelN').textContent = STATS.level || 1;
}
function setDuration(v){
  S.duration = clamp(Math.round(v), 1, 240);
  $('#durBig').textContent = S.openEnded ? '∞' : S.duration;
  $$('#presets .chip').forEach(b => b.classList.toggle('chip-on', !S.openEnded && +b.textContent === S.duration));
  saveSettings({ duration:S.duration, openEnded:S.openEnded });
}
function allOpenings(){
  const custom = (CONTENT.custom_openings || []).map(c => ({
    id:'c'+c.id, title_th:c.title_th || 'บทของฉัน', title_en:c.title_en || c.title_th || 'My text',
    body_th:c.body_th, body_en:c.body_en || c.body_th
  }));
  return (CONTENT.openings || []).concat(custom);
}
function allPraise(){
  const custom = (CONTENT.custom_praise || []).map(c => ({ th:c.body_th, en:c.body_en || c.body_th }));
  return (CONTENT.praise || []).concat(custom);
}

/* ═══════════════ หน้าบันทึก ═══════════════ */
const MOODS = ['😖','😕','😐','🙂','😌'];
function renderLog(){
  // กราฟ 14 วัน
  const bars = $('#barChart'); bars.innerHTML = '';
  const daily = STATS.daily || {};
  const days = [];
  for (let i=13;i>=0;i--){ const d = new Date(); d.setDate(d.getDate()-i); days.push(dstr(d)); }
  const max = Math.max(S.dailyGoal || 20, ...days.map(d => daily[d] || 0));
  days.forEach(d => {
    const v = daily[d] || 0;
    const col = document.createElement('div');
    col.className = 'flex-1 flex flex-col items-center gap-1 group';
    col.innerHTML =
      '<div class="w-full flex-1 flex items-end">' +
        '<div class="w-full rounded-t-md transition-all duration-500" style="height:' +
          (max ? Math.max(v ? 6 : 2, v/max*100) : 2) + '%;background:' + (v ? 'var(--a)' : 'currentColor') +
          ';opacity:' + (v ? .9 : .12) + '" title="' + d + ' — ' + Math.round(v) + ' min"></div>' +
      '</div>' +
      '<div class="text-[9px] opacity-45 tabnum">' + d.slice(8) + '</div>';
    bars.appendChild(col);
  });

  // รายการ
  const list = $('#logList'); list.innerHTML = '';
  if (!SESSIONS.length){
    list.innerHTML = '<div class="text-center py-10 opacity-50 text-sm">' + t('no_sessions') + '</div>';
    $('#btnMoreLog').classList.add('hidden');
    return;
  }
  SESSIONS.slice(0, LOG_LIMIT).forEach(s => {
    const d = new Date(s.started_at);
    const row = document.createElement('div');
    row.className = 'num rounded-2xl p-3.5 flex gap-3 items-start';
    const stars = s.rating ? '★'.repeat(s.rating) + '<span class="opacity-25">' + '★'.repeat(5-s.rating) + '</span>' : '';
    row.innerHTML =
      '<div class="w-11 h-11 rounded-xl grid place-items-center shrink-0 text-lg" style="background:var(--a-dim)">' +
        (s.completed ? '🧘' : '🌤') + '</div>' +
      '<div class="min-w-0 flex-1">' +
        '<div class="flex items-baseline gap-2 flex-wrap">' +
          '<span class="font-semibold tabnum">' + Math.round(s.actual_seconds/60) + ' ' + t('min') + '</span>' +
          '<span class="text-xs opacity-50 tabnum">' + d.toLocaleDateString(S.lang==='en'?'en-GB':'th-TH') +
            ' · ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + '</span>' +
          (stars ? '<span class="text-xs" style="color:var(--a)">' + stars + '</span>' : '') +
        '</div>' +
        (s.mood_before || s.mood_after ?
          '<div class="text-sm mt-1">' + (s.mood_before ? MOODS[s.mood_before-1] : '') +
          (s.mood_after ? ' <span class="opacity-40 text-xs">→</span> ' + MOODS[s.mood_after-1] : '') + '</div>' : '') +
        (s.notes ? '<div class="text-sm opacity-70 mt-1.5 whitespace-pre-line">' + escapeHtml(s.notes) + '</div>' : '') +
      '</div>' +
      '<button data-del="' + s.id + '" class="opacity-35 hover:opacity-100 text-sm px-1">✕</button>';
    list.appendChild(row);
  });
  $$('#logList [data-del]').forEach(b => b.onclick = async () => {
    if (!confirm(t('confirm_del'))) return;
    await api('/api/session/' + b.dataset.del, 'DELETE');
    toast(t('deleted'), '🗑'); await refresh();
  });
  $('#btnMoreLog').classList.toggle('hidden', SESSIONS.length <= LOG_LIMIT);
}
function escapeHtml(s){ return String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

/* ═══════════════ หน้าความก้าวหน้า ═══════════════ */
function renderProgress(){
  $('#lvBadge').textContent = STATS.level || 1;
  $('#lvTitle').textContent = S.lang === 'en' ? (STATS.level_title_en||'') : (STATS.level_title_th||'');
  $('#xpNow').textContent = (STATS.xp || 0).toLocaleString();
  const cur = STATS.xp_in_level || 0, need = STATS.xp_for_next || 100;
  $('#xpBar').style.width = clamp(cur/need*100, 2, 100) + '%';
  $('#xpLabel').textContent = cur + ' / ' + need + ' XP';
  $('#xpNext').textContent = (S.lang==='en'?'Next: Lv.':'ถัดไป: ระดับ ') + ((STATS.level||1)+1);

  const tiles = [
    ['🧘', STATS.total_sessions || 0, t('st_sessions')],
    ['⏱', humanMin(STATS.total_minutes || 0), t('st_time')],
    ['🔥', (STATS.streak || 0) + ' ' + t('days'), t('st_streak')],
    ['🏆', (STATS.longest_streak || 0) + ' ' + t('days'), t('st_longest')],
    ['📏', humanMin(STATS.avg_minutes || 0), t('st_avg')],
    ['📅', humanMin(STATS.month_minutes || 0), t('st_month')],
    ['⭐', (STATS.avg_rating ? STATS.avg_rating.toFixed(1) : '—'), t('st_rating')],
    ['🌄', humanMin(STATS.best_day || 0), t('st_best')],
    ['☀️', humanMin(STATS.today_minutes || 0), t('st_today')],
  ];
  $('#statGrid').innerHTML = tiles.map(x =>
    '<div class="card rounded-2xl p-4"><div class="text-lg">' + x[0] + '</div>' +
    '<div class="text-xl font-bold tabnum mt-1">' + x[1] + '</div>' +
    '<div class="text-[11px] opacity-55 mt-0.5">' + x[2] + '</div></div>').join('');

  // ปฏิทิน 18 สัปดาห์
  const hm = $('#heatmap'); hm.innerHTML = '';
  const daily = STATS.daily || {}, goal = S.dailyGoal || 20;
  const end = new Date(); end.setHours(0,0,0,0);
  const start = new Date(end); start.setDate(start.getDate() - (17*7 + end.getDay()));
  for (let d = new Date(start); d <= end; d.setDate(d.getDate()+1)){
    const key = dstr(d), v = daily[key] || 0;
    const ratio = goal ? v/goal : 0;
    const op = v === 0 ? 0 : ratio < .34 ? .3 : ratio < .67 ? .55 : ratio < 1 ? .78 : 1;
    const cell = document.createElement('i');
    cell.className = 'w-3 h-3 rounded-[3px] block' + (v===0 ? ' bg-black/10 dark:bg-white/10' : '');
    if (v) cell.style.cssText = 'background:var(--a);opacity:' + op;
    cell.title = key + ' — ' + Math.round(v) + ' min';
    hm.appendChild(cell);
  }

  // เหรียญตรา
  const earned = new Set(STATS.badges || []);
  $('#badgeCount').textContent = earned.size + '/' + (CONTENT.badges || []).length;
  $('#badgeGrid').innerHTML = (CONTENT.badges || []).map(b => {
    const on = earned.has(b.id);
    return '<div class="rounded-2xl p-4 text-center transition ' + (on ? '' : 'opacity-40') + '" style="' +
      (on ? 'background:var(--a-dim);border:1px solid var(--a)' : 'background:rgba(127,140,141,.08)') + '">' +
      '<div class="text-3xl mb-1.5' + (on ? '' : ' grayscale') + '">' + b.icon + '</div>' +
      '<div class="text-sm font-semibold">' + L(b) + '</div>' +
      '<div class="text-[11px] opacity-60 mt-0.5">' + (on ? L(b,'desc') : t('locked')) + '</div></div>';
  }).join('');
}

/* ═══════════════ หน้าเรียนรู้ ═══════════════ */
function renderLearn(){
  $('#lessonList').innerHTML = (CONTENT.lessons || []).map((l,i) =>
    '<details class="card rounded-3xl overflow-hidden group"' + (i===0 ? ' open' : '') + '>' +
      '<summary class="cursor-pointer list-none p-5 flex items-center gap-3">' +
        '<span class="w-10 h-10 rounded-xl grid place-items-center text-lg shrink-0" style="background:var(--a-dim)">' + l.icon + '</span>' +
        '<span class="font-semibold font-dhamma">' + L(l,'title') + '</span>' +
        '<span class="ml-auto opacity-40 group-open:rotate-180 transition">▾</span>' +
      '</summary>' +
      '<div class="px-5 pb-6 pt-1 whitespace-pre-line leading-relaxed opacity-85 text-[15px] font-dhamma">' +
        escapeHtml(L(l,'body')) + '</div>' +
    '</details>').join('');

  $('#openingList').innerHTML = allOpenings().map(o =>
    '<div class="num rounded-2xl p-4">' +
      '<div class="font-semibold text-sm mb-1.5 font-dhamma">' + escapeHtml(L(o,'title')) + '</div>' +
      '<div class="text-sm opacity-75 whitespace-pre-line leading-relaxed font-dhamma">' + escapeHtml(L(o,'body')) + '</div>' +
    '</div>').join('');
}

/* ═══════════════ หน้าตั้งค่า (สร้างจากโครงสร้าง) ═══════════════ */
const BELLS = [['bowl','bell_bowl'],['chime','bell_chime'],['gong','bell_gong'],['wood','bell_wood'],['none','bell_none']];
const AMBS  = [['none','amb_none'],['rain','amb_rain'],['ocean','amb_ocean'],['forest','amb_forest'],['hum','amb_hum']];
const SCHEMA = [
  { id:'g_appearance', icon:'🎨', fields:[
    { k:'lang',  label:'f_lang',  type:'select', opts:[['th','ไทย'],['en','English']] },
    { k:'theme', label:'f_theme', type:'select', opts:[['dark','🌙 Dark'],['light','☀️ Light']] },
    { k:'accent', label:'f_accent', type:'accent' },
    { k:'fontScale', label:'f_font', type:'range', min:.85, max:1.3, step:.05 },
  ]},
  { id:'g_time', icon:'⏱', fields:[
    { k:'duration', label:'f_duration', type:'number', min:1, max:240 },
    { k:'prepSeconds', label:'f_prep', type:'number', min:0, max:300, step:5 },
    { k:'intervalBell', label:'f_interval', type:'number', min:0, max:60 },
    { k:'closingSeconds', label:'f_closing', type:'number', min:0, max:600, step:15 },
    { k:'countUp', label:'f_countup', type:'bool' },
    { k:'openEnded', label:'f_openended', type:'bool' },
    { k:'presets', label:'f_presets', type:'csv' },
  ]},
  { id:'g_sound', icon:'🔔', fields:[
    { k:'startBell', label:'f_startbell', type:'select', opts:BELLS, bell:true },
    { k:'startStrikes', label:'f_startstrikes', type:'number', min:1, max:9 },
    { k:'endBell', label:'f_endbell', type:'select', opts:BELLS, bell:true },
    { k:'endStrikes', label:'f_endstrikes', type:'number', min:1, max:9 },
    { k:'intervalSound', label:'f_intervalsound', type:'select', opts:BELLS, bell:true },
    { k:'volume', label:'f_volume', type:'range', min:0, max:1, step:.05 },
    { k:'ambience', label:'f_ambience', type:'select', opts:AMBS },
    { k:'ambienceVolume', label:'f_ambvol', type:'range', min:0, max:.8, step:.05 },
  ]},
  { id:'g_exp', icon:'🪷', fields:[
    { k:'showOpening', label:'f_showopening', type:'bool' },
    { k:'openingId', label:'f_openingid', type:'opening' },
    { k:'showPraise', label:'f_showpraise', type:'bool' },
    { k:'askMood', label:'f_askmood', type:'bool' },
    { k:'showClock', label:'f_showclock', type:'bool' },
    { k:'keepAwake', label:'f_keepawake', type:'bool' },
    { k:'breathGuide', label:'f_breathguide', type:'bool' },
    { k:'breathIn', label:'f_breathin', type:'number', min:2, max:12 },
    { k:'breathOut', label:'f_breathout', type:'number', min:2, max:15 },
  ]},
  { id:'g_goal', icon:'🎯', fields:[
    { k:'dailyGoal', label:'f_dailygoal', type:'number', min:1, max:300 },
    { k:'weeklyGoalDays', label:'f_weekdays', type:'number', min:1, max:7 },
  ]},
];
function renderSettings(){
  const root = $('#settingsRoot'); root.innerHTML = '';
  SCHEMA.forEach(group => {
    const card = document.createElement('div');
    card.className = 'card rounded-3xl p-5 sm:p-6';
    card.innerHTML = '<h3 class="font-semibold mb-4">' + group.icon + '  ' + t(group.id) + '</h3>';
    const box = document.createElement('div'); box.className = 'space-y-4'; card.appendChild(box);

    group.fields.forEach(f => {
      const row = document.createElement('div');
      row.className = 'flex items-center gap-4 flex-wrap';
      const lab = document.createElement('label');
      lab.className = 'text-sm flex-1 min-w-[10rem]'; lab.textContent = t(f.label);
      row.appendChild(lab);
      let input;

      if (f.type === 'bool'){
        input = document.createElement('input'); input.type = 'checkbox';
        input.className = 'w-5 h-5 accent-emerald-500'; input.checked = !!S[f.k];
        input.onchange = () => commit(f.k, input.checked);
      } else if (f.type === 'select'){
        input = document.createElement('select');
        input.className = 'field rounded-lg px-3 py-2 text-sm w-44';
        f.opts.forEach(([v, lbl]) => input.add(new Option(TXT[lbl] ? t(lbl) : lbl, v)));
        input.value = S[f.k];
        input.onchange = () => { commit(f.k, input.value); if (f.bell) Snd.bell(input.value, 1); };
      } else if (f.type === 'opening'){
        input = document.createElement('select');
        input.className = 'field rounded-lg px-3 py-2 text-sm w-44';
        input.add(new Option(t('random_pick'), 'random'));
        allOpenings().forEach(o => input.add(new Option(L(o,'title'), o.id)));
        input.value = S[f.k] || 'random';
        input.onchange = () => commit(f.k, input.value);
      } else if (f.type === 'range'){
        const wrap = document.createElement('div'); wrap.className = 'flex items-center gap-3 w-44';
        input = document.createElement('input'); input.type='range';
        input.min=f.min; input.max=f.max; input.step=f.step; input.value=S[f.k];
        input.className = 'flex-1';
        const out = document.createElement('span');
        out.className = 'text-xs opacity-60 tabnum w-9 text-right';
        out.textContent = (+S[f.k]).toFixed(2).replace(/0+$/,'').replace(/\.$/,'');
        input.oninput = () => { out.textContent = (+input.value).toFixed(2).replace(/0+$/,'').replace(/\.$/,''); };
        input.onchange = () => { commit(f.k, +input.value); if (f.k==='volume') Snd.bell(S.startBell,1); };
        wrap.append(input, out); row.appendChild(wrap); box.appendChild(row); return;
      } else if (f.type === 'accent'){
        const wrap = document.createElement('div'); wrap.className = 'flex gap-2 flex-wrap';
        Object.entries(ACCENTS).forEach(([name, cols]) => {
          const dot = document.createElement('button');
          dot.className = 'w-8 h-8 rounded-full transition' + (S.accent===name ? ' ring-2 ring-offset-2 ring-offset-transparent' : '');
          dot.style.background = 'linear-gradient(140deg,' + cols[0] + ',' + cols[1] + ')';
          if (S.accent === name) dot.style.boxShadow = '0 0 0 3px ' + cols[0] + '66';
          dot.onclick = () => { commit('accent', name); renderSettings(); };
          wrap.appendChild(dot);
        });
        row.appendChild(wrap); box.appendChild(row); return;
      } else if (f.type === 'csv'){
        input = document.createElement('input'); input.type='text';
        input.className = 'field rounded-lg px-3 py-2 text-sm w-44 tabnum';
        input.value = (S[f.k] || []).join(', ');
        input.onchange = () => commit(f.k, input.value.split(',').map(x=>parseInt(x.trim(),10)).filter(x=>x>0).slice(0,10));
      } else {
        input = document.createElement('input'); input.type='number';
        input.min=f.min ?? 0; input.max=f.max ?? 999; input.step=f.step ?? 1;
        input.className = 'field rounded-lg px-3 py-2 text-sm w-24 tabnum text-center';
        input.value = S[f.k];
        input.onchange = () => commit(f.k, clamp(+input.value, f.min ?? 0, f.max ?? 999));
      }
      row.appendChild(input); box.appendChild(row);
    });
    root.appendChild(card);
  });
}
function commit(k, v){
  S[k] = v;
  saveSettings({ [k]:v });
  applyTheme(); applyI18n();
  if (k === 'lang' || k === 'accent') { renderAll(); }
  else { renderSit(); }
}
let saveTimer = null, pending = {};
function saveSettings(patch){
  Object.assign(pending, patch);
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    const p = pending; pending = {};
    try { S = await api('/api/settings', 'POST', p); } catch(e){}
  }, 350);
}

/* ═══════════════ บทของฉัน ═══════════════ */
function renderCustom(){
  const items = (CONTENT.custom_openings || []).map(x => ({...x, kind:'opening'}))
    .concat((CONTENT.custom_praise || []).map(x => ({...x, kind:'praise'})));
  $('#ccList').innerHTML = items.length ? items.map(c =>
    '<div class="num rounded-xl p-3 flex gap-3 items-start text-sm">' +
      '<span class="text-xs px-2 py-0.5 rounded-md shrink-0" style="background:var(--a-dim)">' +
        (c.kind === 'opening' ? t('kind_opening') : t('kind_praise')) + '</span>' +
      '<div class="flex-1 min-w-0">' +
        (c.title_th ? '<div class="font-semibold">' + escapeHtml(c.title_th) + '</div>' : '') +
        '<div class="opacity-70 whitespace-pre-line">' + escapeHtml(c.body_th) + '</div></div>' +
      '<button data-cc="' + c.id + '" class="opacity-40 hover:opacity-100">✕</button></div>').join('')
    : '<div class="text-xs opacity-45 text-center py-3">—</div>';
  $$('#ccList [data-cc]').forEach(b => b.onclick = async () => {
    await api('/api/content/' + b.dataset.cc, 'DELETE'); await refresh(); toast(t('deleted'), '🗑');
  });
}

/* ═══════════════ ตัวจับเวลา ═══════════════ */
const T = {
  phase:'idle', phaseStart:0, pauseAccum:0, pausedAt:0,
  plannedSec:0, addedSec:0, sitSeconds:0, completed:false,
  moodBefore:null, rating:null, moodAfter:null, sessionId:null,
  tickId:null, nextInterval:0, nextReminder:0, wake:null, breathId:null
};
const elapsed = () => (Date.now() - T.phaseStart - T.pauseAccum) / 1000;

function openOpening(){
  Snd.ensure();
  if (!S.showOpening){ startPrep(); return; }
  const list = allOpenings();
  let o = list.find(x => x.id === S.openingId);
  if (!o) o = list[Math.floor(Math.random()*list.length)];
  $('#opTitle').textContent = L(o,'title');
  $('#opBody').textContent = L(o,'body');
  $('#moodBeforeWrap').classList.toggle('hidden', !S.askMood);
  T.moodBefore = null;
  $('#moodBefore').innerHTML = MOODS.map((m,i) =>
    '<button data-m="' + (i+1) + '" class="text-3xl opacity-40 hover:opacity-100 transition">' + m + '</button>').join('');
  $$('#moodBefore [data-m]').forEach(b => b.onclick = () => {
    T.moodBefore = +b.dataset.m;
    $$('#moodBefore [data-m]').forEach(x => x.classList.toggle('opacity-40', x !== b));
    $$('#moodBefore [data-m]').forEach(x => x.style.transform = x===b ? 'scale(1.25)' : 'scale(1)');
  });
  show('#ovOpening');
}
function show(sel){ const e = $(sel); e.classList.remove('hidden'); e.classList.add('flex'); }
function hide(sel){ const e = $(sel); e.classList.add('hidden'); e.classList.remove('flex'); }

async function startPrep(){
  hide('#ovOpening');
  Snd.ensure();
  T.plannedSec = S.openEnded ? 0 : S.duration * 60;
  T.addedSec = 0; T.sitSeconds = 0; T.completed = false; T.sessionId = null;
  T.rating = null; T.moodAfter = null;
  T.startedAt = new Date().toISOString();
  $('#ovSession').classList.remove('hidden');
  document.body.style.overflow = 'hidden';

  if (S.keepAwake && 'wakeLock' in navigator){
    try { T.wake = await navigator.wakeLock.request('screen'); } catch(e){}
  }
  // วงกลมนำลมหายใจ
  const bg = $('#breathGuide');
  bg.style.display = S.breathGuide ? 'block' : 'none';
  bg.style.setProperty('--bd', ((S.breathIn||4) + (S.breathOut||6)) + 's');
  startBreathText();

  if ((S.prepSeconds || 0) > 0){
    T.phase = 'prep'; T.phaseStart = Date.now(); T.pauseAccum = 0;
    setPhaseLabel();
  } else { beginSit(); }
  if (!T.tickId) T.tickId = setInterval(tick, 200);
  Snd.startAmbience();
}
function beginSit(){
  T.phase = 'sit'; T.phaseStart = Date.now(); T.pauseAccum = 0;
  T.nextInterval = (S.intervalBell || 0) * 60;
  T.nextReminder = 75;
  setPhaseLabel();
  Snd.bell(S.startBell, S.startStrikes);
}
function setPhaseLabel(){
  const k = T.phase === 'prep' ? 'ph_prep' : T.phase === 'closing' ? 'ph_closing'
          : T.phase === 'paused' ? 'ph_pause' : 'ph_sit';
  $('#sesPhase').textContent = t(k);
  $('#sesPause').textContent = T.phase === 'paused' ? '▶' : '⏸';
}
function startBreathText(){
  clearInterval(T.breathId);
  if (!S.breathGuide){ $('#sesBreath').textContent = ''; return; }
  const ci = (S.breathIn||4)*1000, co = (S.breathOut||6)*1000;
  const cycle = () => {
    $('#sesBreath').textContent = t('breath_in');
    setTimeout(()=>{ $('#sesBreath').textContent = t('breath_out'); }, ci);
  };
  cycle();
  T.breathId = setInterval(cycle, ci + co);
}
function tick(){
  const now = new Date();
  $('#sesClock').textContent = S.showClock ? pad(now.getHours()) + ':' + pad(now.getMinutes()) : '';
  if (T.phase === 'paused' || T.phase === 'idle') return;
  const e = elapsed();

  if (T.phase === 'prep'){
    const rem = (S.prepSeconds||0) - e;
    $('#sesTime').textContent = Math.ceil(Math.max(0,rem));
    $('#sesSub').textContent = t('ph_prep');
    $('#sesRing').style.strokeDashoffset = 854.5 * (1 - clamp(e/(S.prepSeconds||1),0,1));
    if (rem <= 0) beginSit();
    return;
  }

  if (T.phase === 'sit'){
    const total = T.plannedSec + T.addedSec;
    T.sitSeconds = e;
    if (S.openEnded){
      $('#sesTime').textContent = mmss(e);
      $('#sesSub').textContent = '∞';
      $('#sesRing').style.strokeDashoffset = 854.5 * (1 - (e % 60)/60);
    } else {
      $('#sesTime').textContent = S.countUp ? mmss(e) : mmss(total - e);
      $('#sesSub').textContent = (S.countUp ? mmss(total-e) + ' ' + (S.lang==='en'?'left':'เหลือ')
                                            : Math.round(total/60) + ' ' + t('min'));
      $('#sesRing').style.strokeDashoffset = 854.5 * (1 - clamp(e/total,0,1));
    }
    if (T.nextInterval && e >= T.nextInterval && (S.openEnded || e < total - 3)){
      Snd.bell(S.intervalSound, 1);
      T.nextInterval += (S.intervalBell||0)*60;
    }
    if (e >= T.nextReminder){
      const r = CONTENT.reminders || [];
      if (r.length){
        const el = $('#sesReminder');
        el.textContent = L(r[Math.floor(Math.random()*r.length)]);
        el.style.opacity = '.55';
        setTimeout(()=>{ el.style.opacity = '0'; }, 7000);
      }
      T.nextReminder += 150;
    }
    if (!S.openEnded && e >= total) endSit(true);
    return;
  }

  if (T.phase === 'closing'){
    const rem = (S.closingSeconds||0) - e;
    $('#sesTime').textContent = mmss(Math.max(0,rem));
    $('#sesSub').textContent = t('ph_closing');
    $('#sesRing').style.strokeDashoffset = 854.5 * (1 - clamp(e/(S.closingSeconds||1),0,1));
    if (rem <= 0) finishUp();
  }
}
function endSit(completed){
  T.completed = !!completed;
  T.sitSeconds = T.phase === 'sit' ? elapsed() : T.sitSeconds;
  Snd.bell(S.endBell, S.endStrikes);
  if ((S.closingSeconds||0) > 0){
    T.phase = 'closing'; T.phaseStart = Date.now(); T.pauseAccum = 0;
    setPhaseLabel();
    $('#sesReminder').textContent = t('metta_text');
    $('#sesReminder').style.opacity = '.7';
  } else {
    setTimeout(finishUp, 900);
  }
}
async function finishUp(){
  clearInterval(T.tickId); T.tickId = null;
  clearInterval(T.breathId);
  T.phase = 'idle';
  Snd.stopAmbience();
  if (T.wake){ try{ T.wake.release(); }catch(e){} T.wake = null; }
  $('#ovSession').classList.add('hidden');
  document.body.style.overflow = '';

  const secs = Math.round(T.sitSeconds);
  if (secs < 20){ toast(S.lang==='en' ? 'Too short to log' : 'สั้นเกินกว่าจะบันทึก', '🌱'); await refresh(); return; }

  let res;
  try {
    res = await api('/api/session', 'POST', {
      started_at: T.startedAt,
      planned_seconds: Math.round(T.plannedSec + T.addedSec),
      actual_seconds: secs,
      completed: T.completed ? 1 : 0,
      technique: S.technique,
      mood_before: T.moodBefore
    });
  } catch(e){ toast('Error', '⚠'); return; }
  T.sessionId = res.id;
  STATS = res.stats;

  // หน้าจอสรุป
  $('#fiDuration').textContent = mmss(secs);
  const praise = allPraise();
  $('#fiPraise').style.display = S.showPraise ? 'block' : 'none';
  if (S.showPraise && praise.length){
    const p = praise[Math.floor(Math.random()*praise.length)];
    $('#fiPraise').textContent = L(p);
  }
  $('#fiXp').innerHTML =
    '<span class="px-3 py-1.5 rounded-xl" style="background:var(--a-dim)">✨ ' + t('xp_gained') + ' <b class="tabnum">+' + res.xp_gained + '</b> XP</span>' +
    '<span class="px-3 py-1.5 rounded-xl num">⭐ ' + t('lv') + ' <b class="tabnum">' + STATS.level + '</b></span>' +
    '<span class="px-3 py-1.5 rounded-xl num">🔥 <b class="tabnum">' + STATS.streak + '</b> ' + t('days') + '</span>';

  const nb = res.new_badges || [];
  $('#fiBadges').innerHTML = nb.map(b =>
    '<div class="rounded-2xl p-3 flex items-center gap-3 fade-up" style="background:var(--a-dim);border:1px solid var(--a)">' +
      '<span class="text-2xl">' + b.icon + '</span><div><div class="text-xs opacity-65">' + t('new_badge') + '</div>' +
      '<div class="font-semibold text-sm">' + L(b) + '</div></div></div>').join('');
  if (nb.length) nb.forEach((_,i) => setTimeout(()=>Snd.strike('chime', 0, .6), i*450));

  $('#fiMoodWrap').classList.toggle('hidden', !S.askMood);
  T.moodAfter = null; T.rating = null;
  $('#moodAfter').innerHTML = MOODS.map((m,i) =>
    '<button data-m="' + (i+1) + '" class="text-3xl opacity-40 transition">' + m + '</button>').join('');
  $$('#moodAfter [data-m]').forEach(b => b.onclick = () => {
    T.moodAfter = +b.dataset.m;
    $$('#moodAfter [data-m]').forEach(x => { x.classList.toggle('opacity-40', x!==b); x.style.transform = x===b?'scale(1.25)':'scale(1)'; });
  });
  $('#rateStars').innerHTML = [1,2,3,4,5].map(n =>
    '<button data-r="' + n + '" class="opacity-25 transition">★</button>').join('');
  $$('#rateStars [data-r]').forEach(b => b.onclick = () => {
    T.rating = +b.dataset.r;
    $$('#rateStars [data-r]').forEach(x => {
      const on = +x.dataset.r <= T.rating;
      x.classList.toggle('opacity-25', !on);
      x.style.color = on ? 'var(--a)' : '';
    });
  });
  $('#fiNotes').value = '';
  show('#ovFinish');
}
function togglePause(){
  if (T.phase === 'paused'){
    T.pauseAccum += Date.now() - T.pausedAt;
    T.phase = T.prevPhase; setPhaseLabel();
    $('#breathGuide').style.animationPlayState = 'running';
  } else if (T.phase !== 'idle'){
    T.prevPhase = T.phase; T.pausedAt = Date.now(); T.phase = 'paused'; setPhaseLabel();
    $('#breathGuide').style.animationPlayState = 'paused';
  }
}

/* ═══════════════ โหลดข้อมูล & เริ่มต้น ═══════════════ */
async function refresh(){
  const d = await api('/api/bootstrap');
  S = d.settings; STATS = d.stats; CONTENT = d.content; SESSIONS = d.sessions;
  applyTheme(); applyI18n(); renderAll();
}
function renderAll(){
  applyI18n();
  renderSit(); renderLog(); renderProgress(); renderLearn(); renderSettings(); renderCustom();
}

function bind(){
  $('#btnTheme').onclick = () => { S.theme = S.theme === 'light' ? 'dark' : 'light'; commit('theme', S.theme); };
  $('#btnLang').onclick  = () => { S.lang = S.lang === 'en' ? 'th' : 'en'; commit('lang', S.lang); };
  $$('.tab').forEach(b => b.onclick = () => showTab(b.dataset.tab));

  $('#durRange').oninput = e => { S.duration = +e.target.value; $('#durBig').textContent = S.duration;
    $$('#presets .chip').forEach(b => b.classList.toggle('chip-on', +b.textContent === S.duration)); };
  $('#durRange').onchange = e => setDuration(+e.target.value);
  $('#openEnded').onchange = e => { S.openEnded = e.target.checked; renderSit(); saveSettings({openEnded:S.openEnded}); };
  ['prepSeconds','intervalBell','closingSeconds'].forEach(k => {
    $('#'+k).onchange = e => { S[k] = clamp(+e.target.value||0, 0, 600); e.target.value = S[k]; saveSettings({[k]:S[k]}); };
  });
  $('#showOpening').onchange = e => { S.showOpening = e.target.checked; saveSettings({showOpening:S.showOpening}); };
  $('#openingId').onchange  = e => { S.openingId = e.target.value; saveSettings({openingId:S.openingId}); };

  $('#btnStart').onclick = () => { Snd.ensure(); openOpening(); };
  $('#opCancel').onclick = () => hide('#ovOpening');
  $('#opGo').onclick = () => startPrep();

  $('#sesPause').onclick = togglePause;
  $('#sesAdd').onclick = () => { T.addedSec += 60; toast('+1 ' + t('min'), '⏱'); };
  $('#sesStop').onclick = () => {
    if (T.phase === 'closing'){ finishUp(); return; }
    if (T.phase === 'prep'){ // ยกเลิกก่อนเริ่มจริง
      clearInterval(T.tickId); T.tickId=null; clearInterval(T.breathId); T.phase='idle';
      Snd.stopAmbience(); $('#ovSession').classList.add('hidden'); document.body.style.overflow=''; return;
    }
    if (T.phase === 'paused') togglePause();
    endSit(!S.openEnded && elapsed() >= (T.plannedSec + T.addedSec) - 2);
  };

  $('#fiSave').onclick = async () => {
    await api('/api/session/' + T.sessionId, 'PATCH', {
      mood_after: T.moodAfter, rating: T.rating, notes: $('#fiNotes').value.trim()
    });
    hide('#ovFinish'); toast(t('saved')); await refresh();
  };
  $('#fiSkip').onclick = async () => {
    if (T.sessionId) await api('/api/session/' + T.sessionId, 'DELETE');
    hide('#ovFinish'); toast(t('discarded'), '🗑'); await refresh();
  };

  $('#btnMoreLog').onclick = () => { LOG_LIMIT += 20; renderLog(); };
  $('#btnExportCsv').onclick  = () => window.open('/api/export.csv','_blank');
  $('#btnExportJson').onclick = () => window.open('/api/export.json','_blank');

  $('#btnTestBell').onclick = () => { Snd.ensure(); Snd.bell(S.startBell, 1); };
  $('#btnResetSettings').onclick = async () => { S = await api('/api/settings/reset','POST'); applyTheme(); renderAll(); toast(t('settings_saved')); };
  $('#btnWipe').onclick = async () => {
    if (!confirm(t('confirm_wipe'))) return;
    await api('/api/sessions','DELETE'); await refresh(); toast(t('deleted'),'🗑');
  };

  $('#btnAddCC').onclick = async () => {
    const body = $('#ccBody').value.trim(); if (!body) return;
    await api('/api/content','POST', { kind:$('#ccKind').value, title_th:$('#ccTitle').value.trim(), body_th:body });
    $('#ccBody').value=''; $('#ccTitle').value='';
    await refresh(); toast(t('saved'));
  };

  document.addEventListener('keydown', e => {
    if (e.code === 'Space' && !$('#ovSession').classList.contains('hidden')
        && !['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)){
      e.preventDefault(); togglePause();
    }
    if (e.key === 'Escape' && !$('#ovOpening').classList.contains('hidden')) hide('#ovOpening');
  });
  document.addEventListener('visibilitychange', async () => {
    if (!document.hidden && T.wake === null && S.keepAwake && T.phase !== 'idle' && 'wakeLock' in navigator){
      try { T.wake = await navigator.wakeLock.request('screen'); } catch(e){}
    }
  });
}

(async function init(){
  try { await refresh(); } catch(e){ console.error(e); }
  bind();
  showTab(localStorage.getItem('satiTab') || 'sit');
})();
</script>
</body>
</html>
"""

PAGE = HTML_HEAD + HTML_BODY + HTML_JS + HTML_JS2


# ─────────────────────────────────────────────────────────────
#  สถิติ + ระบบเกม / Stats & gamification
# ─────────────────────────────────────────────────────────────
def xp_to_next(level):
    """XP ที่ต้องใช้เพื่อขึ้นจากระดับ level ไป level+1"""
    return 60 + 40 * (level - 1)


def level_from_xp(xp):
    level, rest = 1, int(xp)
    while rest >= xp_to_next(level) and level < 99:
        rest -= xp_to_next(level)
        level += 1
    return level, rest, xp_to_next(level)


def compute_stats():
    db = get_db()
    rows = db.execute(
        "SELECT day, hour, actual_seconds, completed, rating, notes "
        "FROM sessions ORDER BY started_at"
    ).fetchall()

    today = date.today()
    daily = {}
    per_day_count = {}
    total_sec = 0
    ratings = []
    notes_count = 0
    longest_single = 0
    early = night = False

    for r in rows:
        mins = r["actual_seconds"] / 60.0
        daily[r["day"]] = daily.get(r["day"], 0.0) + mins
        per_day_count[r["day"]] = per_day_count.get(r["day"], 0) + 1
        total_sec += r["actual_seconds"]
        if r["rating"]:
            ratings.append(r["rating"])
        if (r["notes"] or "").strip():
            notes_count += 1
        longest_single = max(longest_single, r["actual_seconds"])
        if r["hour"] < 7:
            early = True
        if r["hour"] >= 21:
            night = True

    days_set = set(daily.keys())

    # streak ปัจจุบัน
    streak = 0
    cur = today
    if cur.isoformat() not in days_set:
        cur = today - timedelta(days=1)
    while cur.isoformat() in days_set:
        streak += 1
        cur -= timedelta(days=1)

    # streak ยาวที่สุด
    longest = 0
    run = 0
    prev = None
    for d in sorted(days_set):
        dd = date.fromisoformat(d)
        run = run + 1 if prev and (dd - prev).days == 1 else 1
        longest = max(longest, run)
        prev = dd

    def span_minutes(days):
        start = today - timedelta(days=days - 1)
        return sum(v for k, v in daily.items() if date.fromisoformat(k) >= start)

    total_min = total_sec / 60.0
    n = len(rows)
    xp = int(round(total_min)) + 5 * n
    level, in_level, need = level_from_xp(xp)
    ti = min(level, len(LEVEL_TITLES)) - 1

    earned = []
    if n >= 1:   earned.append("first")
    if n >= 10:  earned.append("sit10")
    if n >= 50:  earned.append("sit50")
    if n >= 100: earned.append("sit100")
    if total_min >= 60:   earned.append("min60")
    if total_min >= 600:  earned.append("min600")
    if total_min >= 3000: earned.append("min3000")
    if longest >= 3:  earned.append("streak3")
    if longest >= 7:  earned.append("streak7")
    if longest >= 30: earned.append("streak30")
    if early: earned.append("early")
    if night: earned.append("night")
    if longest_single >= 30 * 60: earned.append("long30")
    if longest_single >= 60 * 60: earned.append("long60")
    if any(c >= 2 for c in per_day_count.values()): earned.append("twice")
    if notes_count >= 10: earned.append("journal")

    return {
        "total_sessions": n,
        "total_minutes": round(total_min, 1),
        "today_minutes": round(daily.get(today.isoformat(), 0.0), 1),
        "week_minutes": round(span_minutes(7), 1),
        "month_minutes": round(span_minutes(30), 1),
        "avg_minutes": round(total_min / n, 1) if n else 0,
        "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else 0,
        "best_day": round(max(daily.values()), 1) if daily else 0,
        "longest_single": longest_single,
        "streak": streak,
        "longest_streak": longest,
        "daily": {k: round(v, 1) for k, v in daily.items()},
        "xp": xp,
        "level": level,
        "xp_in_level": in_level,
        "xp_for_next": need,
        "level_title_th": LEVEL_TITLES[ti][0],
        "level_title_en": LEVEL_TITLES[ti][1],
        "badges": earned,
    }


def custom_content(kind):
    db = get_db()
    rows = db.execute(
        "SELECT * FROM custom_content WHERE kind=? ORDER BY id DESC", (kind,)
    ).fetchall()
    return [dict(r) for r in rows]


def content_payload():
    return {
        "openings": OPENINGS,
        "praise": PRAISE,
        "lessons": LESSONS,
        "reminders": REMINDERS,
        "badges": BADGES,
        "custom_openings": custom_content("opening"),
        "custom_praise": custom_content("praise"),
    }


def recent_sessions(limit=400):
    rows = get_db().execute(
        "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────
#  เส้นทาง / Routes
# ─────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return Response(PAGE, mimetype="text/html; charset=utf-8")


@app.route("/api/bootstrap")
def api_bootstrap():
    return jsonify({
        "settings": load_settings(),
        "stats": compute_stats(),
        "content": content_payload(),
        "sessions": recent_sessions(),
    })


@app.route("/api/settings", methods=["POST"])
def api_settings():
    return jsonify(save_settings(request.get_json(silent=True) or {}))


@app.route("/api/settings/reset", methods=["POST"])
def api_settings_reset():
    db = get_db()
    db.execute("DELETE FROM settings WHERE key='app'")
    db.commit()
    return jsonify(load_settings())


@app.route("/api/session", methods=["POST"])
def api_session_create():
    d = request.get_json(silent=True) or {}
    before = compute_stats()

    try:
        started = datetime.fromisoformat(str(d.get("started_at", "")).replace("Z", "+00:00"))
        started = started.astimezone() if started.tzinfo else started
    except (ValueError, TypeError):
        started = datetime.now()

    actual = max(0, int(d.get("actual_seconds") or 0))
    db = get_db()
    cur = db.execute(
        "INSERT INTO sessions(started_at, day, hour, planned_seconds, actual_seconds, completed,"
        " technique, mood_before, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (
            started.isoformat(timespec="seconds"),
            started.date().isoformat(),
            started.hour,
            max(0, int(d.get("planned_seconds") or 0)),
            actual,
            1 if d.get("completed") else 0,
            str(d.get("technique") or "anapanasati"),
            d.get("mood_before"),
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    db.commit()

    after = compute_stats()
    fresh = set(after["badges"]) - set(before["badges"])
    return jsonify({
        "id": cur.lastrowid,
        "stats": after,
        "xp_gained": after["xp"] - before["xp"],
        "new_badges": [b for b in BADGES if b["id"] in fresh],
    })


@app.route("/api/session/<int:sid>", methods=["PATCH"])
def api_session_update(sid):
    d = request.get_json(silent=True) or {}
    db = get_db()
    db.execute(
        "UPDATE sessions SET mood_after=?, rating=?, notes=? WHERE id=?",
        (d.get("mood_after"), d.get("rating"), str(d.get("notes") or "")[:2000], sid),
    )
    db.commit()
    return jsonify({"ok": True, "stats": compute_stats()})


@app.route("/api/session/<int:sid>", methods=["DELETE"])
def api_session_delete(sid):
    db = get_db()
    db.execute("DELETE FROM sessions WHERE id=?", (sid,))
    db.commit()
    return jsonify({"ok": True, "stats": compute_stats()})


@app.route("/api/sessions", methods=["GET", "DELETE"])
def api_sessions():
    db = get_db()
    if request.method == "DELETE":
        db.execute("DELETE FROM sessions")
        db.commit()
        return jsonify({"ok": True, "stats": compute_stats()})
    return jsonify(recent_sessions(int(request.args.get("limit", 400))))


@app.route("/api/content", methods=["POST"])
def api_content_add():
    d = request.get_json(silent=True) or {}
    kind = "praise" if d.get("kind") == "praise" else "opening"
    body = str(d.get("body_th") or "").strip()[:4000]
    if not body:
        return jsonify({"error": "empty"}), 400
    db = get_db()
    db.execute(
        "INSERT INTO custom_content(kind,title_th,title_en,body_th,body_en,created_at) VALUES(?,?,?,?,?,?)",
        (
            kind,
            str(d.get("title_th") or "")[:200],
            str(d.get("title_en") or d.get("title_th") or "")[:200],
            body,
            str(d.get("body_en") or body)[:4000],
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/content/<int:cid>", methods=["DELETE"])
def api_content_delete(cid):
    db = get_db()
    db.execute("DELETE FROM custom_content WHERE id=?", (cid,))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/export.json")
def api_export_json():
    payload = json.dumps(
        {"exported_at": datetime.now().isoformat(timespec="seconds"),
         "stats": compute_stats(), "sessions": recent_sessions(100000)},
        ensure_ascii=False, indent=2,
    )
    return Response(
        payload, mimetype="application/json; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=sati-export.json"},
    )


@app.route("/api/export.csv")
def api_export_csv():
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "started_at", "day", "hour", "planned_min", "actual_min",
                "completed", "technique", "mood_before", "mood_after", "rating", "notes"])
    for s in reversed(recent_sessions(100000)):
        w.writerow([
            s["id"], s["started_at"], s["day"], s["hour"],
            round(s["planned_seconds"] / 60, 1), round(s["actual_seconds"] / 60, 1),
            s["completed"], s["technique"], s["mood_before"], s["mood_after"],
            s["rating"], (s["notes"] or "").replace("\n", " "),
        ])
    return Response(
        "﻿" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=sati-sessions.csv"},
    )


# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    try:  # คอนโซล Windows บางเครื่องไม่รองรับ UTF-8
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print("\n  Sati - meditation timer running at  http://127.0.0.1:%d\n" % port)
    app.run(host="127.0.0.1", port=port, debug=False)
