"""
Builds the 9 standard GHS pictogram icons as SVG files: red diamond border,
white fill, black glyph, per GHS Rev. 5/OSHA HazCom 2012 spec.

IMPORTANT: These are hand-built schematic renderings (correct shape,
proportion, and color per the GHS spec) -- NOT the official OSHA/UN artwork
files. They're suitable for prototyping label layout and internal review.
Before anything goes to print, swap these for OSHA's official pictogram
graphics (osha.gov publishes the authoritative versions) to be safe on
compliance, since regulators can be particular about exact symbol
rendering.
"""

import os

DIAMOND_FRAME = '''<polygon points="100,4 196,100 100,196 4,100" fill="white" stroke="#E2231A" stroke-width="12"/>'''

GLYPHS = {
    "GHS01_explosive": '''
        <circle cx="100" cy="115" r="28" fill="black"/>
        <g stroke="black" stroke-width="5">
            <line x1="100" y1="60" x2="100" y2="80"/>
            <line x1="60" y1="75" x2="78" y2="90"/>
            <line x1="140" y1="75" x2="122" y2="90"/>
            <line x1="50" y1="115" x2="72" y2="115"/>
            <line x1="150" y1="115" x2="128" y2="115"/>
            <line x1="60" y1="150" x2="78" y2="138"/>
            <line x1="140" y1="150" x2="122" y2="138"/>
        </g>
    ''',
    "GHS02_flammable": '''
        <path d="M100 55 C80 85 70 105 85 130 C80 120 90 115 95 122
                 C92 108 105 100 105 85 C118 100 125 118 112 138
                 C130 128 138 108 128 88 C138 95 140 110 132 122
                 C142 105 138 78 100 55 Z" fill="black"/>
    ''',
    "GHS03_oxidizing": '''
        <circle cx="100" cy="130" r="26" fill="none" stroke="black" stroke-width="7"/>
        <path d="M100 50 C85 75 78 92 90 112 C87 104 95 100 98 106
                 C96 96 106 90 106 78 C116 90 121 104 111 118
                 C124 110 130 95 122 80 C130 85 132 96 126 105
                 C134 92 130 70 100 50 Z" fill="black"/>
    ''',
    "GHS04_gas_cylinder": '''
        <rect x="82" y="60" width="36" height="90" rx="6" fill="none" stroke="black" stroke-width="7"/>
        <rect x="90" y="46" width="20" height="16" fill="black"/>
        <line x1="82" y1="80" x2="118" y2="80" stroke="black" stroke-width="4"/>
    ''',
    "GHS05_corrosive": '''
        <path d="M70 55 L130 55 L122 95 L78 95 Z" fill="none" stroke="black" stroke-width="6"/>
        <line x1="85" y1="95" x2="70" y2="140" stroke="black" stroke-width="6"/>
        <line x1="115" y1="95" x2="130" y2="140" stroke="black" stroke-width="6"/>
        <path d="M60 140 q10 -14 20 0 q10 -14 20 0" fill="none" stroke="black" stroke-width="5"/>
        <path d="M100 140 q10 -14 20 0 q10 -14 20 0" fill="none" stroke="black" stroke-width="5"/>
        <line x1="55" y1="150" x2="60" y2="165" stroke="black" stroke-width="4"/>
        <line x1="145" y1="150" x2="140" y2="165" stroke="black" stroke-width="4"/>
    ''',
    "GHS06_toxic": '''
        <g stroke="black" stroke-width="9" stroke-linecap="round">
            <line x1="60" y1="115" x2="140" y2="165"/>
            <line x1="140" y1="115" x2="60" y2="165"/>
        </g>
        <g fill="black" stroke-width="5">
            <circle cx="72" cy="118" r="6"/><circle cx="128" cy="118" r="6"/>
            <circle cx="72" cy="162" r="6"/><circle cx="128" cy="162" r="6"/>
            <circle cx="100" cy="140" r="6"/>
        </g>
        <path d="M100 45 C72 45 60 66 60 88 C60 104 68 114 76 120
                 L76 128 L124 128 L124 120 C132 114 140 104 140 88
                 C140 66 128 45 100 45 Z" fill="black"/>
        <ellipse cx="82" cy="86" rx="10" ry="13" fill="white"/>
        <ellipse cx="118" cy="86" rx="10" ry="13" fill="white"/>
        <polygon points="100,92 94,108 106,108" fill="white"/>
        <g fill="black">
            <rect x="80" y="120" width="7" height="9"/>
            <rect x="93" y="120" width="7" height="9"/>
            <rect x="106" y="120" width="7" height="9"/>
            <rect x="119" y="120" width="7" height="9"/>
        </g>
    ''',
    "GHS07_exclamation": '''
        <line x1="100" y1="55" x2="100" y2="122" stroke="black" stroke-width="14" stroke-linecap="round"/>
        <circle cx="100" cy="148" r="9" fill="black"/>
    ''',
    "GHS08_health_hazard": '''
        <ellipse cx="100" cy="100" rx="30" ry="38" fill="none" stroke="black" stroke-width="6"/>
        <path d="M75 75 q25 30 50 0" fill="none" stroke="black" stroke-width="5"/>
        <line x1="100" y1="85" x2="100" y2="150" stroke="black" stroke-width="5"/>
        <path d="M78 150 q22 24 44 0" fill="none" stroke="black" stroke-width="5"/>
        <path d="M65 60 l14 90 M135 60 l-14 90" stroke="black" stroke-width="4" opacity="0.0"/>
    ''',
    "GHS09_environment": '''
        <line x1="40" y1="155" x2="120" y2="155" stroke="black" stroke-width="6"/>
        <line x1="72" y1="155" x2="72" y2="80" stroke="black" stroke-width="6"/>
        <path d="M72 80 C55 82 45 95 42 108 C58 110 70 100 72 88 Z" fill="black"/>
        <path d="M72 95 C89 97 100 108 103 120 C87 122 74 113 72 100 Z" fill="black"/>
        <path d="M72 115 C55 118 46 130 44 142 C60 144 71 135 72 122 Z" fill="black"/>
        <path d="M118 130 C140 122 150 128 156 138 C148 148 136 148 128 140
                 C132 148 130 156 122 158 C120 148 122 138 118 130 Z" fill="black"/>
        <circle cx="146" cy="134" r="2.5" fill="white"/>
    ''',
}

TITLES = {
    "GHS01_explosive": "Explosive",
    "GHS02_flammable": "Flammable",
    "GHS03_oxidizing": "Oxidizing",
    "GHS04_gas_cylinder": "Gas Under Pressure",
    "GHS05_corrosive": "Corrosive",
    "GHS06_toxic": "Toxic",
    "GHS07_exclamation": "Harmful / Irritant",
    "GHS08_health_hazard": "Health Hazard",
    "GHS09_environment": "Environmental Hazard",
}


def build_all(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    for name, glyph in GLYPHS.items():
        code = name.split("_")[0]
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="200" height="200">
<title>{code} - {TITLES[name]}</title>
{DIAMOND_FRAME}
{glyph}
</svg>'''
        path = os.path.join(out_dir, f"{name}.svg")
        with open(path, "w") as f:
            f.write(svg)
    print(f"Built {len(GLYPHS)} pictograms in {out_dir}")


if __name__ == "__main__":
    build_all(os.path.dirname(os.path.abspath(__file__)))
