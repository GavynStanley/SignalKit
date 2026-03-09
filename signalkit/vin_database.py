"""
VIN (Vehicle Identification Number) database and decoder.

WMI data sourced from NHTSA vPIC API (vpic.nhtsa.dot.gov).
Covers 380+ WMI codes across all major automotive brands.

Model year decoding follows the standard VIN position 10 chart.
"""

# World Manufacturer Identifier — first 3 characters of VIN
WMI_MAKE = {
    # ── Toyota / Lexus / Scion ──
    "JTD": "Toyota", "JTE": "Toyota", "JTK": "Toyota", "JTL": "Toyota",
    "JTM": "Toyota", "JTN": "Toyota", "JT2": "Toyota", "JT3": "Toyota",
    "JT4": "Toyota", "JT5": "Toyota", "JT6": "Toyota", "JT8": "Toyota",
    "2T1": "Toyota", "2T3": "Toyota", "3TM": "Toyota", "3TY": "Toyota",
    "4T1": "Toyota", "4T3": "Toyota", "4T4": "Toyota",
    "5TB": "Toyota", "5TD": "Toyota", "5TE": "Toyota", "5TF": "Toyota",
    "5YF": "Toyota", "58A": "Toyota", "7MU": "Toyota", "7SV": "Toyota",
    "NMT": "Toyota", "SB1": "Toyota", "VNK": "Toyota",
    "JTH": "Lexus", "JTJ": "Lexus", "2T2": "Lexus",

    # ── Honda / Acura ──
    "JHM": "Honda", "JHL": "Honda", "JH1": "Honda", "JH2": "Honda",
    "JH3": "Honda", "JR2": "Honda",
    "1HG": "Honda", "1HF": "Honda", "2HG": "Honda", "2HJ": "Honda",
    "2HK": "Honda", "2HN": "Honda", "2HU": "Honda",
    "3CZ": "Honda", "3DH": "Honda", "3HD": "Honda", "3HG": "Honda",
    "3H1": "Honda", "5FN": "Honda", "5J6": "Honda", "5J7": "Honda",
    "5KB": "Honda", "7FA": "Honda",
    "19X": "Honda", "19V": "Acura",
    "SHH": "Honda", "SHS": "Honda",
    "YC1": "Honda", "ZDC": "Honda", "MLH": "Honda",
    "LAL": "Honda", "RLH": "Honda", "VTM": "Honda", "VTD": "Honda",
    "LWB": "Honda", "9C2": "Honda", "478": "Honda",
    "JH4": "Acura", "19U": "Acura", "2HH": "Acura",
    "5FR": "Acura", "5FP": "Acura", "5FS": "Acura",
    "5J8": "Acura", "5KC": "Acura",

    # ── Ford / Lincoln / Mercury ──
    "1FA": "Ford", "1FB": "Ford", "1FC": "Ford", "1FD": "Ford",
    "1FL": "Ford", "1FM": "Ford", "1FT": "Ford", "1F1": "Ford", "1F7": "Ford",
    "2FA": "Ford", "2FB": "Ford", "2FC": "Ford", "2FD": "Ford",
    "2FM": "Ford", "2FT": "Ford",
    "3FA": "Ford", "3FB": "Ford", "3FC": "Ford", "3FD": "Ford",
    "3FE": "Ford", "3FM": "Ford", "3FT": "Ford", "3MA": "Ford",
    "4F2": "Ford", "4F3": "Ford", "4F4": "Ford",
    "5LT": "Ford", "5LD": "Ford", "6MP": "Ford", "7A5": "Ford",
    "WF0": "Ford", "WF1": "Ford", "NM0": "Ford", "MAJ": "Ford", "9BF": "Ford",
    "1LN": "Lincoln", "1L1": "Lincoln", "1LJ": "Lincoln",
    "2LN": "Lincoln", "2LJ": "Lincoln", "2L1": "Lincoln", "2LM": "Lincoln",
    "3LN": "Lincoln", "5LM": "Lincoln", "5L1": "Lincoln",
    "1ME": "Mercury", "2ME": "Mercury", "3ME": "Mercury",

    # ── Nissan / Infiniti ──
    "JN1": "Nissan", "JN3": "Nissan", "JN6": "Nissan", "JN8": "Nissan",
    "JNR": "Nissan", "JNT": "Nissan", "JNX": "Nissan", "SJK": "Nissan",
    "1N4": "Nissan", "1N6": "Nissan",
    "3N1": "Nissan", "3N6": "Nissan", "3N8": "Nissan", "3PC": "Nissan",
    "5N1": "Nissan", "5BZ": "Nissan",
    "JNK": "Infiniti", "5N3": "Infiniti",

    # ── Hyundai / Genesis ──
    "KMH": "Hyundai", "KME": "Hyundai", "KMF": "Hyundai", "KMU": "Hyundai",
    "KM8": "Hyundai", "KPH": "Hyundai",
    "5NP": "Hyundai", "5NT": "Hyundai", "5NM": "Hyundai",
    "U5Y": "Hyundai", "3H3": "Hyundai", "145": "Hyundai",
    "PFD": "Hyundai", "7YA": "Hyundai",
    "KMT": "Genesis",

    # ── Kia ──
    "KNA": "Kia", "KNC": "Kia", "KND": "Kia", "KNH": "Kia", "KNJ": "Kia",
    "5XX": "Kia", "5XY": "Kia", "3KP": "Kia", "3KM": "Kia",

    # ── General Motors — Chevrolet ──
    "1G1": "Chevrolet", "2G1": "Chevrolet", "3G1": "Chevrolet",
    "1GA": "Chevrolet", "2GA": "Chevrolet", "5GA": "Chevrolet",
    "1GB": "Chevrolet", "2GB": "Chevrolet", "3GB": "Chevrolet",
    "1GC": "Chevrolet", "2GC": "Chevrolet", "3GC": "Chevrolet",
    "1GD": "Chevrolet", "2GD": "Chevrolet", "3GD": "Chevrolet",
    "1GE": "Chevrolet", "2GE": "Chevrolet",
    "1GG": "Chevrolet", "3GG": "Chevrolet",
    "1GH": "Chevrolet", "2GH": "Chevrolet",
    "1GM": "Chevrolet", "3GM": "Chevrolet",
    "1GN": "Chevrolet", "2GN": "Chevrolet", "3GN": "Chevrolet",
    "1G0": "Chevrolet", "1G5": "Chevrolet", "3G5": "Chevrolet",
    "2C1": "Chevrolet", "2C2": "Chevrolet", "2CG": "Chevrolet",
    "2CK": "Chevrolet", "2CN": "Chevrolet", "2CT": "Chevrolet",
    "2G8": "Chevrolet", "3G7": "Chevrolet", "3GP": "Chevrolet", "3GS": "Chevrolet",
    "4G1": "Chevrolet", "4GD": "Chevrolet", "4GL": "Chevrolet",
    "4KB": "Chevrolet", "4KD": "Chevrolet", "4KL": "Chevrolet",
    "4NS": "Chevrolet", "4NT": "Chevrolet", "4NU": "Chevrolet",
    "4W1": "Chevrolet", "4W5": "Chevrolet",
    "5G2": "Chevrolet", "5G3": "Chevrolet", "5G5": "Chevrolet", "5G8": "Chevrolet",
    "5GR": "Chevrolet", "5GT": "Chevrolet", "5GZ": "Chevrolet",
    "5S3": "Chevrolet", "6G1": "Chevrolet",
    "JG1": "Chevrolet", "JGC": "Chevrolet", "J8C": "Chevrolet",
    "KL1": "Chevrolet", "KL2": "Chevrolet", "KL7": "Chevrolet", "KL8": "Chevrolet",
    "LRB": "Chevrolet", "LRE": "Chevrolet", "ADM": "Chevrolet",

    # ── General Motors — GMC ──
    "1GT": "GMC", "2GT": "GMC", "3GT": "GMC", "4GT": "GMC",
    "1GJ": "GMC", "2GJ": "GMC",
    "1GK": "GMC", "2GK": "GMC", "3GK": "GMC",
    "2G0": "GMC", "3G0": "GMC",
    "5GD": "GMC", "5GN": "GMC",
    "JGT": "GMC", "J8T": "GMC",

    # ── General Motors — Buick ──
    "1G4": "Buick", "2G4": "Buick", "3G4": "Buick",
    "2G5": "Buick", "4G5": "Buick", "KL4": "Buick",

    # ── General Motors — Cadillac ──
    "1G6": "Cadillac", "2G6": "Cadillac",
    "1GY": "Cadillac", "3GY": "Cadillac", "6G3": "Cadillac",

    # ── General Motors — Pontiac (discontinued) ──
    "1G2": "Pontiac", "2G2": "Pontiac", "3G2": "Pontiac",
    "6G2": "Pontiac", "JG2": "Pontiac",

    # ── General Motors — Saturn / Oldsmobile / Hummer ──
    "1G8": "Saturn", "1G3": "Oldsmobile", "2G3": "Oldsmobile", "3G3": "Oldsmobile",
    "1G7": "Hummer", "2G7": "Hummer",

    # ── Stellantis — Chrysler ──
    "1C3": "Chrysler", "2C3": "Chrysler", "3C3": "Chrysler", "4C3": "Chrysler",
    "1C5": "Chrysler", "2C5": "Chrysler", "3C5": "Chrysler",
    "1C8": "Chrysler", "2C8": "Chrysler", "3C8": "Chrysler",
    "2CA": "Chrysler", "3CA": "Chrysler",
    "1P5": "Chrysler", "2P5": "Chrysler", "3P5": "Chrysler",
    "1XM": "Chrysler", "2XM": "Chrysler", "2V8": "Chrysler",
    "3B3": "Chrysler", "3B5": "Chrysler", "4E3": "Chrysler", "3E4": "Chrysler",

    # ── Stellantis — Dodge ──
    "1B3": "Dodge", "2B3": "Dodge", "4B3": "Dodge", "JB3": "Dodge",
    "1B4": "Dodge", "2B4": "Dodge", "3B4": "Dodge",
    "1B5": "Dodge", "2B5": "Dodge",
    "1B6": "Dodge", "2B6": "Dodge", "3B6": "Dodge",
    "1B7": "Dodge", "2B7": "Dodge", "3B7": "Dodge",
    "1B8": "Dodge", "2B8": "Dodge", "3B8": "Dodge",
    "1B2": "Dodge", "2B2": "Dodge", "3B2": "Dodge",
    "1D3": "Dodge", "2D3": "Dodge", "3D3": "Dodge",
    "1D4": "Dodge", "2D4": "Dodge", "3D4": "Dodge",
    "1D5": "Dodge", "2D5": "Dodge", "3D5": "Dodge",
    "1D8": "Dodge", "2D8": "Dodge", "3D8": "Dodge",
    "1A3": "Dodge", "2A3": "Dodge", "3A3": "Dodge",
    "1A4": "Dodge", "1A6": "Dodge", "2A6": "Dodge", "3A6": "Dodge",
    "1A7": "Dodge", "2A7": "Dodge", "3A7": "Dodge",
    "1A8": "Dodge", "2A8": "Dodge", "3A8": "Dodge",
    "1E3": "Dodge", "2E3": "Dodge", "3E3": "Dodge",
    "1P3": "Dodge", "2P3": "Dodge", "3P3": "Dodge",
    "1P6": "Dodge", "2P6": "Dodge", "3P6": "Dodge",
    "1Z3": "Dodge", "1Z4": "Dodge", "1Z7": "Dodge",
    "1A2": "Dodge", "2A2": "Dodge", "3A2": "Dodge",
    "1C2": "Dodge", "2D2": "Dodge", "3D2": "Dodge",

    # ── Stellantis — Jeep ──
    "1C4": "Jeep", "2C4": "Jeep", "3C4": "Jeep",
    "1J2": "Jeep", "1J3": "Jeep", "1J4": "Jeep", "2J4": "Jeep", "3J4": "Jeep",
    "1J5": "Jeep", "2J5": "Jeep", "3J5": "Jeep",
    "1J6": "Jeep", "2J6": "Jeep", "3J6": "Jeep",
    "1J7": "Jeep", "1J8": "Jeep",
    "1P4": "Jeep", "2P4": "Jeep", "3P4": "Jeep",
    "1Z6": "Jeep", "1Z8": "Jeep", "2E4": "Jeep", "2V4": "Jeep",
    "MN3": "Jeep", "MP3": "Jeep", "JE3": "Jeep",

    # ── Stellantis — Ram ──
    "1C6": "Ram", "2C6": "Ram", "3C6": "Ram",
    "1C7": "Ram", "2C7": "Ram", "3C7": "Ram",
    "1D2": "Ram", "1D6": "Ram", "2D6": "Ram", "3D6": "Ram",
    "1D7": "Ram", "3D7": "Ram",
    "1JC": "Ram", "1JD": "Ram", "1JT": "Ram",
    "1P7": "Ram", "2P7": "Ram", "3P7": "Ram",

    # ── Stellantis — Fiat / Alfa Romeo ──
    "ZFA": "Fiat", "ZFB": "Fiat", "ZAC": "Fiat",
    "ZAR": "Alfa Romeo", "ZAS": "Alfa Romeo",

    # ── Subaru ──
    "JF1": "Subaru", "JF2": "Subaru", "JF3": "Subaru", "JF4": "Subaru",
    "4S3": "Subaru", "4S4": "Subaru",

    # ── Mazda ──
    "JM1": "Mazda", "JM2": "Mazda", "JM3": "Mazda",
    "JC1": "Mazda", "JC2": "Mazda",
    "3MZ": "Mazda", "3MY": "Mazda", "3MD": "Mazda", "3MV": "Mazda",
    "7MM": "Mazda",

    # ── BMW / Mini ──
    "WBA": "BMW", "WBS": "BMW", "WBX": "BMW", "WBY": "BMW",
    "WB1": "BMW", "WB3": "BMW", "WB4": "BMW", "WB5": "BMW", "WZ1": "BMW",
    "WAP": "BMW",
    "3MW": "BMW", "3MF": "BMW",
    "4US": "BMW", "5UM": "BMW", "5UX": "BMW", "5YM": "BMW",
    "WMW": "Mini", "WMZ": "Mini",

    # ── Mercedes-Benz ──
    "WDB": "Mercedes-Benz", "WDC": "Mercedes-Benz", "WDD": "Mercedes-Benz",
    "WDA": "Mercedes-Benz", "WDW": "Mercedes-Benz", "WDX": "Mercedes-Benz",
    "WDY": "Mercedes-Benz", "WDZ": "Mercedes-Benz", "WDP": "Mercedes-Benz",
    "WDR": "Mercedes-Benz",
    "WD0": "Mercedes-Benz", "WD1": "Mercedes-Benz", "WD2": "Mercedes-Benz",
    "WD3": "Mercedes-Benz", "WD4": "Mercedes-Benz", "WD5": "Mercedes-Benz",
    "WD6": "Mercedes-Benz", "WD7": "Mercedes-Benz", "WD8": "Mercedes-Benz",
    "WME": "Mercedes-Benz", "WCD": "Mercedes-Benz", "WYB": "Mercedes-Benz",
    "W1K": "Mercedes-Benz", "W1H": "Mercedes-Benz", "W1N": "Mercedes-Benz",
    "W1W": "Mercedes-Benz", "W1X": "Mercedes-Benz", "W1Y": "Mercedes-Benz",
    "W1Z": "Mercedes-Benz",
    "W2W": "Mercedes-Benz", "W2X": "Mercedes-Benz", "W2Y": "Mercedes-Benz",
    "W2Z": "Mercedes-Benz",
    "55S": "Mercedes-Benz", "1MB": "Mercedes-Benz", "1VH": "Mercedes-Benz",
    "3F6": "Mercedes-Benz", "4JG": "Mercedes-Benz", "9DB": "Mercedes-Benz",
    "8BN": "Mercedes-Benz", "8BR": "Mercedes-Benz", "8BT": "Mercedes-Benz",
    "8BU": "Mercedes-Benz",

    # ── Audi ──
    "WAU": "Audi", "WUA": "Audi", "WA1": "Audi", "WU1": "Audi", "TRU": "Audi",

    # ── Volkswagen ──
    "WVW": "Volkswagen", "WVG": "Volkswagen",
    "WV1": "Volkswagen", "WV2": "Volkswagen", "WV3": "Volkswagen",
    "1V1": "Volkswagen", "1V2": "Volkswagen", "1VW": "Volkswagen",
    "3VW": "Volkswagen", "3VV": "Volkswagen", "9BW": "Volkswagen",

    # ── Volvo ──
    "YV1": "Volvo", "YV2": "Volvo", "YV3": "Volvo",
    "YV4": "Volvo", "YV5": "Volvo", "YV6": "Volvo",
    "YB1": "Volvo", "YB3": "Volvo",
    "LVY": "Volvo", "LYV": "Volvo",
    "4V1": "Volvo", "4V2": "Volvo", "4V3": "Volvo",
    "4V4": "Volvo", "4V5": "Volvo", "4V6": "Volvo",
    "4VA": "Volvo", "4VB": "Volvo", "4VC": "Volvo",
    "4VD": "Volvo", "4VE": "Volvo", "4VG": "Volvo",
    "4VH": "Volvo", "4VJ": "Volvo", "4VK": "Volvo", "4VM": "Volvo",
    "7JR": "Volvo", "7JD": "Volvo",
    "1WA": "Volvo", "1WB": "Volvo", "1WD": "Volvo",
    "1WU": "Volvo", "1WX": "Volvo", "1WY": "Volvo",
    "2PC": "Volvo", "3CE": "Volvo", "9BV": "Volvo",

    # ── Porsche ──
    "WP0": "Porsche", "WP1": "Porsche",

    # ── Tesla ──
    "5YJ": "Tesla", "7G2": "Tesla", "7SA": "Tesla", "SFZ": "Tesla",

    # ── Rivian ──
    "7FC": "Rivian", "7PD": "Rivian",

    # ── Lucid ──
    "50E": "Lucid", "7UU": "Lucid",

    # ── Mitsubishi ──
    "JA3": "Mitsubishi", "JA4": "Mitsubishi", "JA7": "Mitsubishi",
    "JB4": "Mitsubishi", "JB7": "Mitsubishi",
    "JE4": "Mitsubishi", "JJ3": "Mitsubishi",
    "JL6": "Mitsubishi", "JL7": "Mitsubishi", "JLS": "Mitsubishi",
    "JP3": "Mitsubishi", "JP4": "Mitsubishi", "JP7": "Mitsubishi",
    "JW6": "Mitsubishi", "JW7": "Mitsubishi",
    "4A3": "Mitsubishi", "4A4": "Mitsubishi", "4P3": "Mitsubishi",
    "6MM": "Mitsubishi", "ML3": "Mitsubishi", "TYB": "Mitsubishi",

    # ── Jaguar / Land Rover ──
    "SAJ": "Jaguar", "SAD": "Jaguar",
    "SAL": "Land Rover",

    # ── Italian Exotics ──
    "ZFF": "Ferrari", "ZFD": "Ferrari", "ZSG": "Ferrari",
    "ZHW": "Lamborghini", "ZPB": "Lamborghini",
    "ZAM": "Maserati", "ZC2": "Maserati", "ZN6": "Maserati",

    # ── British Luxury ──
    "SCB": "Bentley", "SJA": "Bentley",
    "SCA": "Rolls-Royce", "SLA": "Rolls-Royce",
    "SCF": "Aston Martin", "SD7": "Aston Martin",
    "SBM": "McLaren",
    "SCC": "Lotus", "LJU": "Lotus",

    # ── Suzuki ──
    "JS1": "Suzuki", "JS2": "Suzuki", "JS3": "Suzuki", "JS4": "Suzuki",
    "JSA": "Suzuki", "JSK": "Suzuki", "JSL": "Suzuki",
    "JKS": "Suzuki", "JG7": "Suzuki",
    "2S2": "Suzuki", "2S3": "Suzuki", "5SA": "Suzuki", "5Z6": "Suzuki",
    "KL5": "Suzuki",
    "LC6": "Suzuki", "LM1": "Suzuki", "LM4": "Suzuki", "LN1": "Suzuki",
    "MLC": "Suzuki", "RFD": "Suzuki", "RK6": "Suzuki", "RK7": "Suzuki",
    "VTT": "Suzuki",

    # ── Isuzu ──
    "JAA": "Isuzu", "JAB": "Isuzu", "JAC": "Isuzu", "JAE": "Isuzu",
    "JAL": "Isuzu", "JAM": "Isuzu",
    "J81": "Isuzu", "J87": "Isuzu", "J8B": "Isuzu", "J8D": "Isuzu", "J8Z": "Isuzu",
    "4S1": "Isuzu", "4S2": "Isuzu", "4S5": "Isuzu", "4S6": "Isuzu",
    "722": "Isuzu",

    # ── Saab (discontinued) ──
    "YS3": "Saab", "YK1": "Saab",

    # ── Opel/Vauxhall (GM Europe) ──
    "W0V": "Opel",

    # ── Harley-Davidson ──
    "1HD": "Harley-Davidson",
}

# ── Manufacturer-specific model codes (VIN position 4) ──────────────────────
KIA_MODELS = {
    "A": "Rio/Pride", "B": "Soul", "C": "Optima/K5", "D": "Sportage",
    "E": "Sorento", "F": "Forte/Cerato", "G": "Niro", "H": "Cadenza/K7",
    "J": "Stinger", "K": "K900/K9", "L": "Telluride", "N": "Seltos",
    "P": "Carnival/Sedona", "R": "EV6", "S": "Forte5/Cerato5",
    "U": "Soul EV",
}

HYUNDAI_MODELS = {
    "A": "Elantra", "B": "Santa Fe", "C": "Sonata", "D": "Tucson",
    "E": "Accent", "F": "Azera/Grandeur", "G": "Veloster",
    "H": "Genesis", "J": "Ioniq", "K": "Palisade", "L": "Santa Cruz",
    "M": "Kona", "N": "Venue",
}

# Kia / Hyundai engine codes (VIN position 8)
KIA_HYUNDAI_ENGINES = {
    "1": "1.6L I4", "2": "2.0L I4", "3": "2.4L I4", "4": "2.0L Turbo I4",
    "5": "1.6L Turbo I4", "6": "3.3L V6", "7": "3.3L Turbo V6",
    "8": "3.5L V6", "9": "3.8L V6", "A": "2.5L I4", "B": "2.5L Turbo I4",
    "C": "1.6L Turbo GDI", "D": "2.0L MPI", "E": "Electric",
    "U": "1.6L Hybrid", "V": "2.0L Hybrid",
}

# VIN position 10 → model year (standard across all manufacturers)
VIN_YEAR = {
    "A": 2010, "B": 2011, "C": 2012, "D": 2013, "E": 2014,
    "F": 2015, "G": 2016, "H": 2017, "J": 2018, "K": 2019,
    "L": 2020, "M": 2021, "N": 2022, "P": 2023, "R": 2024,
    "S": 2025, "T": 2026, "V": 2027, "W": 2028, "X": 2029,
    "Y": 2030, "1": 2031, "2": 2032, "3": 2033, "4": 2034,
    "5": 2035, "6": 2036, "7": 2037, "8": 2038, "9": 2039,
}


def decode_vin(vin):
    """
    Decode a VIN into make, year, and (when possible) model/engine.
    Uses the NHTSA WMI database for make identification.
    Kia and Hyundai get model + engine from VIN positions 4 and 8.
    """
    if not vin or len(vin) < 11:
        return {"vin": vin, "make": None, "year": None,
                "model": None, "engine": None,
                "display": vin or "Unknown"}

    vin = vin.upper().strip()
    result = {"vin": vin}

    # WMI → Make (first 3 chars)
    wmi = vin[:3]
    result["make"] = WMI_MAKE.get(wmi, f"Unknown ({wmi})")

    # Model year (position 10, 0-indexed = 9)
    year_char = vin[9]
    result["year"] = VIN_YEAR.get(year_char, f"Unknown ({year_char})")

    # Model & engine — manufacturer-specific positions
    make_lower = result["make"].lower()
    model_char = vin[3]   # Position 4 (0-indexed = 3)
    engine_char = vin[7]  # Position 8 (0-indexed = 7)

    if "kia" in make_lower:
        result["model"] = KIA_MODELS.get(model_char, f"Unknown ({model_char})")
        result["engine"] = KIA_HYUNDAI_ENGINES.get(engine_char, f"Unknown ({engine_char})")
    elif "hyundai" in make_lower:
        result["model"] = HYUNDAI_MODELS.get(model_char, f"Unknown ({model_char})")
        result["engine"] = KIA_HYUNDAI_ENGINES.get(engine_char, f"Unknown ({engine_char})")
    else:
        result["model"] = None
        result["engine"] = None

    # Build display string
    parts = []
    if isinstance(result.get("year"), int):
        parts.append(str(result["year"]))
    parts.append(result["make"])
    if result.get("model"):
        parts.append(result["model"])
    if result.get("engine"):
        parts.append(result["engine"])
    result["display"] = " ".join(parts)

    return result
