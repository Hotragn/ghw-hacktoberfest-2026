"""Known scam storylines (paraphrased from public consumer-protection guidance, e.g. FTC/FBI IC3 PSAs)."""
STORYLINES = [
    ("Pig-butchering crypto romance", "investment",
     "A friendly stranger texts by mistake then chats every night for weeks, often late at night from overseas. "
     "They build trust and romance, then introduce a crypto investment app showing huge profits. The victim "
     "deposits cash at a bitcoin kiosk again and again; the app balance keeps growing but withdrawals need fees.",
     "Real exchanges never show prices above the market. Never deposit cash into a bitcoin ATM for someone you met online."),
    ("Tech-support refund scam", "impersonation",
     "A pop-up or caller says the computer is hacked or a refund was overpaid. They take remote control, "
     "ask the victim to buy gift cards or withdraw cash, and keep them on the phone for hours.",
     "Microsoft or your bank will never ask for gift cards. Hang up and call a known number."),
    ("Grandparent emergency scam", "impersonation",
     "A late-night call from a crying grandchild or a lawyer says the grandchild is in jail or hurt and needs bail "
     "money urgently and secretly. A courier comes to the door to collect cash.",
     "Hang up and call the grandchild or a parent directly. Nobody legitimate sends a courier for bail cash."),
    ("Government impersonation / safe account", "impersonation",
     "A caller claiming to be the IRS, SSA or a bank fraud department says the money is at risk and must be moved "
     "to a safe account, converted to bitcoin at a kiosk or withdrawn in cash and handed over.",
     "Government agencies never ask you to move money to protect it or pay in crypto."),
    ("Lottery / sweepstakes prize fee", "advance_fee",
     "The victim is told they won a lottery or car but must pay taxes and fees first by wire or gift cards. "
     "Repeated calls from international numbers push more payments.",
     "You never pay to collect a real prize."),
    ("Romance emergency abroad", "romance",
     "An online partner the victim has never met in person talks for hours every night, then has a medical or "
     "customs emergency abroad and needs wire transfers.",
     "Never send money to someone you have not met in person."),
    ("Fake investment recovery", "investment",
     "After losing money, the victim is contacted by a recovery agency that promises to get the crypto back for an "
     "upfront fee paid in bitcoin.",
     "Recovery scams target previous victims; real law enforcement does not charge fees."),
    ("Normal routine (benign)", "benign",
     "Regular daytime calls with family and friends, groceries, pharmacy and utility payments, normal sleep, "
     "no unusual visitors.",
     "No action needed."),
]
CATEGORY_LABELS = {"investment": 1, "impersonation": 2, "advance_fee": 3, "romance": 4, "benign": 9}
