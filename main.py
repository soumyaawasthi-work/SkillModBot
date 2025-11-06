import discord
from discord.ext import commands
from collections import defaultdict
from math import prod
import os
from dotenv import load_dotenv

load_dotenv()

# ---- HERO MULTIPLIERS + VALUES YOU PROVIDED ----
HERO_DATA = {
    "Chenko": [("DamageUp", 101, 0.25)],
    "Amadeus": [("DamageUp", 101, 0.25)],
    "Yeonwoo": [("DamageUp", 101, 0.25)],
    "Amane": [("DamageUp", 102, 0.25)],
    "Howard": [("DefenseUp", 111, 0.20)],
    "Quinn": [("DefenseUp", 111, 0.20)],
    "Gordon": [("DefenseUp", 113, 0.25)],
    "Fahd": [("OppDamageDown", 201, 0.20)],
    "Saul": [("DefenseUp", 112, 0.10), ("DefenseUp", 113, 0.15)],
    "Hilde": [("DefenseUp", 112, 0.10), ("DamageUp", 102, 0.15)],
    "Eric": [("OppDamageDown", 202, 0.20)],
    "Margot": [("DamageUp", 102, 0.25)],
}

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


def compute_factors_from_hero_counts(hero_counts):
    """
    hero_counts: dict e.g. {"Chenko": 4, "Amane": 2}
    Returns per-category dict of {effect_op: total_pct} and final factors.
    """
    # Per-op sums
    per_op = defaultdict(float)  # key: (category, op) -> sum of decimals

    for hero, count in hero_counts.items():
        hero_norm = hero.strip()
        if hero_norm not in HERO_DATA:
            raise KeyError(hero_norm)
        for (cat, op, pct) in HERO_DATA[hero_norm]:
            per_op[(cat, op)] += pct * count

    # Build list of factors per category: multiply across distinct ops
    def category_factor(cat_name):
        # Collect all ops for this category
        factors = []
        for (cat, op), total_pct in per_op.items():
            if cat == cat_name:
                factors.append(1.0 + total_pct)  # (1 + sum_pct_for_this_op)
        return prod(factors) if factors else 1.0

    dmg_factor = category_factor("DamageUp")
    def_factor = category_factor("DefenseUp")
    opp_def_factor = category_factor("OppDefenseDown")
    opp_dmg_factor = category_factor("OppDamageDown")

    return {
        "per_op": per_op,
        "DamageUpFactor": dmg_factor,
        "DefenseUpFactor": def_factor,
        "OppDefenseDownFactor": opp_def_factor,
        "OppDamageDownFactor": opp_dmg_factor
    }


def calculate_skillmod(hero_counts):
    """
    Returns a result dict with SkillMod, percentage outputs, and friendly strings.
    """
    groups = compute_factors_from_hero_counts(hero_counts)
    dmg_f = groups["DamageUpFactor"]
    def_f = groups["DefenseUpFactor"]
    opp_def_f = groups["OppDefenseDownFactor"]
    opp_dmg_f = groups["OppDamageDownFactor"]

    # SkillMod per article
    skillmod = (dmg_f * opp_def_f) / (opp_dmg_f * def_f)

    # Damage dealt % increase vs baseline
    damage_percent_increase = (skillmod - 1.0) * 100.0

    # Damage taken: enemy damage after your OppDamageDown (reduces enemy outgoing)
    # and after your DefenseUp (reduces damage taken).
    # We'll present both as:
    #   final_damage_taken_multiplier = (1 / def_f) * (1 / opp_dmg_f_for_damage_taken)
    # But opp_dmg_f currently is (1 + sums). For damage-taken reduction it's more natural to
    # treat OppDamageDown as multiplicative reduction of enemy damage: factor = 1 / (1 + sum)
    # That would double-count if you used opp_dmg_f both ways, so we'll compute enemy reduction factor:
    if groups["OppDamageDownFactor"] != 0:
        enemy_reduction_factor = 1.0 / groups["OppDamageDownFactor"]
    else:
        enemy_reduction_factor = 1.0

    final_damage_taken_multiplier = (1.0 / def_f) * enemy_reduction_factor
    damage_taken_percent_change = (final_damage_taken_multiplier -
                                   1.0) * 100.0  # negative = less damage taken

    return {
        "SkillMod": skillmod,
        "Damage%Increase": damage_percent_increase,
        "FinalDamageTakenMultiplier": final_damage_taken_multiplier,
        "DamageTaken%Change": damage_taken_percent_change,
        "components": {
            "DamageUpFactor": dmg_f,
            "DefenseUpFactor": def_f,
            "OppDefenseDownFactor": opp_def_f,
            "OppDamageDownFactor": opp_dmg_f,
            "per_op": groups["per_op"]
        }
    }


# -------- Bot commands ----------
@bot.command()
async def heroes(ctx):
    """List available heroes"""
    rows = []
    for h, effects in HERO_DATA.items():
        e = ", ".join(f"{cat}:{op}({pct*100:.0f}%)"
                      for (cat, op, pct) in effects)
        rows.append(f"**{h}** — {e}")
    text = (
        "Available heroes (format = Category:effect_op(percent)):\n\n" +
        "\n".join(rows) +
        "\n\nNote: If you stack joiners with the same effect but different effect_op, "
        "you’ll get a stronger SkillMod than if you use heroes with the same effect "
        "and same effect_op.")
    await ctx.send(text)


@bot.command()
async def skillmod(ctx, *args):
    """
    Usage: !skillmod Chenko 4
           !skillmod Chenko 2 Amane 2
    """
    # parse args pairs hero count
    if len(args) == 0:
        await ctx.send(
            "Usage example: `!skillmod Chenko 4` or `!skillmod Chenko 2 Amane 2`.\nType `!heroes` for list."
        )
        return

    # Accept either pairs or single token like "Chenko:4,Amane:2"
    hero_counts = {}
    try:
        if len(args) == 1 and (":" in args[0] or "," in args[0]):
            # parse "Chenko:2,Amane:2" style
            part = args[0]
            items = [
                p.strip() for p in part.replace(",", " ").split() if p.strip()
            ]
            for it in items:
                if ":" in it:
                    name, cnt = it.split(":", 1)
                    hero_counts[name.strip()] = hero_counts.get(
                        name.strip(), 0) + int(cnt)
                else:
                    # single name -> count 1
                    hero_counts[it] = hero_counts.get(it, 0) + 1
        else:
            # parse pairs
            if len(args) % 2 != 0:
                raise ValueError("Arguments must be pairs: hero count")
            for i in range(0, len(args), 2):
                name = args[i]
                cnt = int(args[i + 1])
                hero_counts[name] = hero_counts.get(name, 0) + cnt
    except Exception as e:
        await ctx.send(
            "❌ Parse error. Use `!skillmod Chenko 4` or `!skillmod Chenko 2 Amane 2` or `!skillmod Chenko:4,Amane:2`"
        )
        return

    # Normalize hero names case-insensitively to allowed keys
    normalized = {}
    for name, cnt in hero_counts.items():
        matched = None
        for h in HERO_DATA.keys():
            if h.lower() == name.lower():
                matched = h
                break
        if not matched:
            await ctx.send(
                f"❌ Unknown hero: `{name}`. Type `!heroes` for the full list.")
            return
        normalized[matched] = normalized.get(matched, 0) + cnt

    # compute
    res = calculate_skillmod(normalized)

    # prepare reply
    comp = res["components"]
    per_op_lines = []
    for (cat, op), tot in comp["per_op"].items():
        per_op_lines.append(f"{cat} op{op}: {tot*100:.1f}% (sum for that op)")

    # --- Friendly Summary ---
    summary_lines = []

    if res["Damage%Increase"] > 0:
        summary_lines.append(
            f"💥 **You’ll deal about {res['Damage%Increase']:.0f}% more damage** than normal."
        )
    else:
        summary_lines.append("😐 **Your damage stays about the same.**")

    if res["DamageTaken%Change"] < 0:
        summary_lines.append(
            f"🛡️ **You’ll take about {abs(res['DamageTaken%Change']):.0f}% less damage** thanks to defense buffs."
        )
    elif res["DamageTaken%Change"] > 0:
        summary_lines.append(
            f"⚠️ **You’ll take about {res['DamageTaken%Change']:.0f}% more damage** than usual."
        )
    else:
        summary_lines.append("🛡️ **No change in damage taken.**")

    # --- Detailed Breakdown ---
    reply = (
        "**🧾 Quick Summary:**\n" + "\n".join(summary_lines) + "\n\n"
        f"**SkillMod:** `{res['SkillMod']:.4f}` (how all buffs multiply together)\n"
        f"**Damage Dealt:** `+{res['Damage%Increase']:.1f}%`\n"
        f"**Damage Taken:** `{res['FinalDamageTakenMultiplier']:.3f}×` ({res['DamageTaken%Change']:.1f}% change)\n\n"
        f"**Breakdown (for advanced players):**\n"
        f"- DamageUp factor → how much your joiners boost attack: {comp['DamageUpFactor']:.3f}\n"
        f"- DefenseUp factor → how much defense reduces damage: {comp['DefenseUpFactor']:.3f}\n"
        f"- OppDefenseDown factor → how much you lower enemy defense: {comp['OppDefenseDownFactor']:.3f}\n"
        f"- OppDamageDown factor → how much you weaken enemy attacks: {comp['OppDamageDownFactor']:.3f}\n\n"
        f"**Per-effect_op totals:**\n" + "\n".join(per_op_lines))

    await ctx.send(reply)


bot_token = os.getenv("DISCORD_BOT_TOKEN")
if bot_token:
    bot.run(bot_token)
else:
    print("Error: DISCORD_BOT_TOKEN not found in environment variables.")
    print("Please add your Discord bot token to the Secrets.")
