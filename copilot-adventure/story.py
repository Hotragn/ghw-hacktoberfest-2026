"""Scenes and choices for The Last Light."""

STORY = {
    "crossroads": {
        "title": "The Crossroads",
        "text": (
            "At dusk, a silver fog rolls across the coast road. Beyond it, a "
            "lighthouse flashes once, then goes dark. Three paths leave the "
            "crossroads."
        ),
        "choices": [
            {"text": "Visit the lantern-lit market.", "target": "market"},
            {"text": "Take the path into the pine forest.", "target": "forest"},
            {"text": "Follow the shore toward the river.", "target": "riverbank"},
        ],
    },
    "market": {
        "title": "The Night Market",
        "text": (
            "Stalls are closing as you arrive. An old mapmaker presses a "
            "brass key into your palm and points inland to the village."
        ),
        "choices": [
            {
                "text": "Accept the brass key and go to the village.",
                "target": "village",
                "gain": ["brass_key"],
            },
            {"text": "Return to the crossroads.", "target": "crossroads"},
        ],
    },
    "forest": {
        "title": "The Pine Forest",
        "text": (
            "A fallen ranger's pack rests beneath a leaning pine. The trail "
            "splits: one branch climbs toward an old mill, the other descends "
            "into a cave."
        ),
        "choices": [
            {
                "text": "Take the ranger's lantern and enter the cave.",
                "target": "cave",
                "gain": ["lantern"],
            },
            {
                "text": "Take the ranger's lantern and head for the old mill.",
                "target": "old_mill",
                "gain": ["lantern"],
            },
            {"text": "Return to the crossroads.", "target": "crossroads"},
        ],
    },
    "riverbank": {
        "title": "The Riverbank",
        "text": (
            "The river has swallowed the stepping stones. A coil of rope is "
            "caught in the reeds, and the old mill stands across the current."
        ),
        "choices": [
            {
                "text": "Take the rope and cross to the old mill.",
                "target": "old_mill",
                "gain": ["rope"],
            },
            {"text": "Return to the crossroads.", "target": "crossroads"},
        ],
    },
    "cave": {
        "title": "The Echoing Cave",
        "text": (
            "Your lantern reveals a stone door marked with the mapmaker's "
            "crest. A narrow passage also winds uphill toward a watchtower."
        ),
        "choices": [
            {
                "text": "Unlock the stone door and enter the hidden vault.",
                "target": "vault",
                "requires": ["brass_key"],
            },
            {"text": "Follow the passage to the watchtower.", "target": "watchtower"},
            {"text": "Return to the forest.", "target": "forest"},
        ],
    },
    "old_mill": {
        "title": "The Old Mill",
        "text": (
            "The mill wheel turns though there is no wind. A stair climbs to "
            "the ridge; a rope bridge leads back across the river."
        ),
        "choices": [
            {"text": "Climb the ridge to the watchtower.", "target": "watchtower"},
            {"text": "Cross back to the riverbank.", "target": "riverbank"},
        ],
    },
    "village": {
        "title": "Bellwether Village",
        "text": (
            "Every door is shut. A bell rings by itself in the empty square. "
            "The archive and the lighthouse road are both open."
        ),
        "choices": [
            {"text": "Search the village archive.", "target": "archive"},
            {"text": "Take the coastal road to the lighthouse.", "target": "lighthouse"},
            {"text": "Return to the market.", "target": "market"},
        ],
    },
    "watchtower": {
        "title": "The Watchtower",
        "text": (
            "From the tower, you see a storm gathering over the headland. "
            "Below, a rope-scarred ledge descends to a garden beneath the tide."
        ),
        "choices": [
            {"text": "Climb toward the storm peak.", "target": "storm_peak"},
            {
                "text": "Use your rope to reach the drowned garden.",
                "target": "drowned_garden",
                "requires": ["rope"],
            },
            {"text": "Return to the old mill.", "target": "old_mill"},
        ],
    },
    "archive": {
        "title": "The Village Archive",
        "text": (
            "A journal explains that the lighthouse flame protects the coast. "
            "Its keeper vanished while carrying a rescue signal to the shore."
        ),
        "choices": [
            {"text": "Carry the journal's signal to the lighthouse.", "target": "ending_rescue"},
            {
                "text": "Open the sealed vault beneath the archive.",
                "target": "vault",
                "requires": ["brass_key"],
            },
            {"text": "Return to the village square.", "target": "village"},
        ],
    },
    "storm_peak": {
        "title": "The Storm Peak",
        "text": (
            "Lightning tears open the clouds. At the summit, a narrow path "
            "drops toward the lighthouse, but the exposed ridge is crumbling."
        ),
        "choices": [
            {"text": "Risk the ridge and descend to the lighthouse.", "target": "lighthouse"},
            {"text": "Signal the storm with your lantern.", "target": "ending_lost"},
            {"text": "Retreat to the watchtower.", "target": "watchtower"},
        ],
    },
    "lighthouse": {
        "title": "The Dark Lighthouse",
        "text": (
            "The lantern room is cold. From the gallery, you can see a rescue "
            "boat offshore—and hear a keeper's voice behind the sealed door."
        ),
        "choices": [
            {"text": "Guide the rescue boat safely to shore.", "target": "ending_rescue"},
            {
                "text": "Unlock the keeper's door with the brass key.",
                "target": "ending_warden",
                "requires": ["brass_key"],
            },
            {"text": "Return to the village.", "target": "village"},
        ],
    },
    "drowned_garden": {
        "title": "The Drowned Garden",
        "text": (
            "Blue flowers glow beneath the waves. At the garden's heart lies "
            "a pearl that hums with the same rhythm as the lighthouse beam."
        ),
        "choices": [
            {
                "text": "Take the moon-pearl and follow its light.",
                "target": "ending_tide",
                "gain": ["moon_pearl"],
            },
            {"text": "Climb back to the watchtower.", "target": "watchtower"},
        ],
    },
    "vault": {
        "title": "The Hidden Vault",
        "text": (
            "Inside the vault, an ancient lens rests beside a map of hidden "
            "coast paths. The lens could restore the lighthouse—or reveal "
            "something older beneath it."
        ),
        "choices": [
            {"text": "Carry the lens to the lighthouse and relight it.", "target": "ending_home"},
            {
                "text": "Use the lens to awaken the ancient keeper.",
                "target": "ending_warden",
            },
            {"text": "Return to the cave.", "target": "cave"},
        ],
    },
    "ending_home": {
        "title": "Ending: A Beacon Home",
        "text": (
            "The ancient lens catches the first glimmer of dawn. The lighthouse "
            "answers with a steady beam, and every lost sailor finds the harbor."
        ),
        "ending": "good",
        "choices": [],
    },
    "ending_rescue": {
        "title": "Ending: The Coast Remembers",
        "text": (
            "Your signal guides the rescue boat through the fog. The keeper "
            "returns, and the village bells ring for the living once more."
        ),
        "ending": "good",
        "choices": [],
    },
    "ending_lost": {
        "title": "Ending: Lost in the Storm",
        "text": (
            "The storm swallows your signal. At dawn, the coast is quiet, and "
            "the lighthouse remains dark."
        ),
        "ending": "bad",
        "choices": [],
    },
    "ending_tide": {
        "title": "Secret Ending: The Tide's Keeper",
        "text": (
            "The moon-pearl opens a path beneath the sea. You accept the "
            "garden's charge and become the hidden keeper of every safe harbor."
        ),
        "ending": "secret",
        "choices": [],
    },
    "ending_warden": {
        "title": "Ending: The Warden's Bargain",
        "text": (
            "The ancient keeper wakes and offers you a place beside it. You "
            "may guard the coast forever, but the village will tell no stories "
            "of what became of you."
        ),
        "ending": "ambiguous",
        "choices": [],
    },
}

START_SCENE = "crossroads"
