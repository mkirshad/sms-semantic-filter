"""Generate a synthetic SMS Backup & Restore file for testing (no real data).

The conversation mixes everyday chat with an example topic -- planning to buy a
used car -- where several messages never mention a car at all.
"""

from datetime import datetime, timedelta
from xml.sax.saxutils import quoteattr

START = datetime(2026, 3, 2, 9, 0)
ADDRESS = "+15555550123"
CONTACT = "Sam"

# (minutes after previous, direction 1=received 2=sent, text, kind)
CONVO = [
    (0, 1, "Morning! You up?", "sms"),
    (3, 2, "Barely. Coffee first \U0001F634", "sms"),
    (40, 1, "Did you call the guy about the Civic?", "sms"),
    (5, 2, "Yeah, he says 4k firm", "sms"),
    (2, 1, "That's steep for that year", "sms"),
    (1, 2, "It's only got 90k on it though", "sms"),
    (3, 1, "Ask if he'll do 3.5 if you pay today", "sms"),
    (60, 2, "My mom's car is in the shop again, I'm driving her to work all week", "sms"),
    (4, 1, "Ugh, that's rough. Tell her I said hi", "sms"),
    (120, 2, "Can you come with me Saturday to look at it?", "sms"),
    (6, 1, "Sure. Bring cash just in case, he won't take Venmo", "sms"),
    (2, 2, "Got it. I'll hit the ATM Friday", "sms"),
    (300, 1, "What are we doing for dinner Sunday?", "sms"),
    (8, 2, "Pizza? The new place on 5th is supposed to be good", "sms"),
    (1, 1, "Yes!! Pizza > everything \U0001F355", "sms"),
    (500, 2, "He texted back. 3.8 and he'll throw in the winter tires", "sms"),
    (3, 1, "Take it. Tires alone are worth a few hundred", "sms"),
    (2, 2, "Ok I told him yes. Picking it up after work", "mms"),
    (240, 1, "Don't forget we have the dentist at 3 tomorrow & you're driving", "sms"),
    (5, 2, "\"Driving\" lol. In my new ride \U0001F60E", "sms"),
    (900, 1, "How's the insurance quote looking?", "sms"),
    (10, 2, "Cheaper than I thought, 92 a month", "sms"),
    (30, 1, "Happy for you. Did you see the game last night?", "sms"),
    (4, 2, "Missed it, was at the DMV for 3 hours \U0001F629", "sms"),
    (2, 1, "Classic. Want to watch the next one at mine?", "sms"),
    (1, 2, "Deal", "sms"),
]


def surrogate_refs(text: str) -> str:
    """Encode characters outside the BMP the way SMS Backup & Restore does."""
    out = []
    for ch in text:
        cp = ord(ch)
        if cp > 0xFFFF:
            cp -= 0x10000
            out.append(f"&#{0xD800 + (cp >> 10)};&#{0xDC00 + (cp & 0x3FF)};")
        else:
            out.append(ch)
    return "".join(out)


def attr(value: str) -> str:
    return surrogate_refs(quoteattr(value))


def main(path: str = "sample-backup.xml") -> None:
    lines = []
    t = START
    for minutes, box, text, kind in CONVO:
        t += timedelta(minutes=minutes)
        ms = int(t.timestamp() * 1000)
        readable = t.strftime("%b %d, %Y %I:%M:%S %p")
        if kind == "sms":
            lines.append(
                f'  <sms protocol="0" address="{ADDRESS}" date="{ms}" type="{box}" subject="null" '
                f'body={attr(text)} toa="null" sc_toa="null" service_center="null" read="1" '
                f'status="-1" locked="0" date_sent="{ms}" sub_id="1" readable_date="{readable}" '
                f'contact_name="{CONTACT}" />'
            )
        else:
            lines.append(
                f'  <mms date="{ms}" rr="null" sub="null" ct_t="application/vnd.wap.multipart.related" '
                f'read_status="null" seen="1" msg_box="{box}" address="{ADDRESS}" sub_cs="null" '
                f'resp_st="null" retr_st="null" d_tm="null" text_only="1" exp="null" locked="0" '
                f'm_id="null" st="null" retr_txt_cs="null" retr_txt="null" creator="null" '
                f'date_sent="0" read="1" m_size="0" rpt_a="null" ct_cls="null" pri="null" sub_id="1" '
                f'tr_id="null" resp_txt="null" ct_l="null" m_cls="null" d_rpt="null" v="18" '
                f'_id="1" m_type="128" readable_date="{readable}" contact_name="{CONTACT}">\n'
                f'    <parts>\n'
                f'      <part seq="0" ct="text/plain" name="null" chset="106" cd="null" fn="null" '
                f'cid="&lt;text0&gt;" cl="text0.txt" ctt_s="null" ctt_t="null" text={attr(text)} />\n'
                f'    </parts>\n'
                f'    <addrs>\n'
                f'      <addr address="{ADDRESS}" type="151" charset="106" />\n'
                f'    </addrs>\n'
                f'  </mms>'
            )
    header = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>\n"
        "<!--File Created By SMS Backup & Restore v10.20.002 on 02/10/2026 09:00:00-->\n"
        "<?xml-stylesheet type=\"text/xsl\" href=\"sms.xsl\"?>\n"
        f'<smses count="{len(CONVO)}" backup_set="00000000-0000-0000-0000-000000000000" '
        f'backup_date="{int(START.timestamp() * 1000)}" type="full">\n'
    )
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(header + "\n".join(lines) + "\n</smses>\n")
    print(f"Wrote {len(CONVO)} messages to {path}")


if __name__ == "__main__":
    import sys
    main(*sys.argv[1:])
