import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

load_dotenv()

HERO_DATA = {
    "Chenko": [("DamageUp", 101)],
    "Amadeus": [("DamageUp", 101)],
    "Yeonwoo": [("DamageUp", 101)],
    "Amane": [("DamageUp", 102)],
    "Howard": [("DefenseUp", 111)],
    "Quinn": [("DefenseUp", 111)],
    "Gordon": [("DefenseUp", 113)],
    "Fahd": [("OppDamageDown", 201)],
    "Saul": [("DefenseUp", 112), ("DefenseUp", 113)],
    "Hilde": [("DefenseUp", 112), ("DamageUp", 102)],
    "Eric": [("OppDamageDown", 202)],
    "Margot": [("DamageUp", 102)],
}

BONUSES = {
    101: 0.375,
    102: 0.25,
    111: 0.333,
    112: 0.375,
    113: 0.5,
    201: 0.25,
    202: 0.375
}

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

def calculate_skillmod(hero_input):
    damage = 0
    defense = 0
    oppdmg = 0

    for hero, count in hero_input.items():
        for effect, code in HERO_DATA.get(hero, []):
            bonus = BONUSES[code] * count

            if "DamageUp" in effect:
                damage += bonus
            elif "DefenseUp" in effect:
                defense += bonus
            elif "OppDamageDown" in effect:
                oppdmg += bonus

    skillmod = (1 + damage) * (1 + defense) * (1 - oppdmg)
    dmg_change = (1 + damage - oppdmg - 1) * 100
    def_change = ((1 / (1 + defense)) - 1) * 100

    return skillmod, dmg_change, def_change

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')

@bot.command()
async def skillmod(ctx, *args):
    hero_input = {}

    for i in range(0, len(args), 2):
        hero = args[i]
        count = int(args[i + 1])
        hero_input[hero] = count

    skillmod, dmg, defp = calculate_skillmod(hero_input)

    await ctx.send(
        f"**SkillMod:** {skillmod:.4f}\n"
        f"**Damage:** {dmg:+.2f}%\n"
        f"**Damage Taken:** {defp:.2f}%"
    )

bot_token = os.getenv("DISCORD_BOT_TOKEN")
if bot_token:
    bot.run(bot_token)
else:
    print("Error: DISCORD_BOT_TOKEN not found in environment variables.")
    print("Please add your Discord bot token to the Secrets.")
