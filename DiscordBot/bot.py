# bot.py
import discord
from discord.ext import commands
import os
import json
import logging
import re
import requests
from report import Report
from uni2ascii import uni2ascii

PERSPECTIVE_SCORE_THRESHOLD = 0.70

# Set up logging to the console
logger = logging.getLogger('discord')
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)

# There should be a file called 'token.json' inside the same folder as this file
token_path = 'tokens.json'
if not os.path.isfile(token_path):
    raise Exception(f"{token_path} not found!")
with open(token_path) as f:
    # If you get an error here, it means your token is formatted incorrectly. Did you put it in quotes?
    tokens = json.load(f)
    discord_token = tokens['discord']
    perspective_key = tokens['perspective']


class ModBot(discord.Client):
    def __init__(self, key):
        intents = discord.Intents.default()
        super().__init__(command_prefix='.', intents=intents)
        self.group_num = None
        self.mod_channels = {} # Map from guild to the mod channel id for that guild
        self.reports = {} # Map from user IDs to the state of their report
        self.perspective_key = key

    async def on_ready(self):
        print(f'{self.user.name} has connected to Discord! It is these guilds:')
        for guild in self.guilds:
            print(f' - {guild.name}')
        print('Press Ctrl-C to quit.')

        # Parse the group number out of the bot's name
        match = re.search('[gG]roup (\d+) [bB]ot', self.user.name)
        if match:
            self.group_num = match.group(1)
        else:
            raise Exception("Group number not found in bot's name. Name format should be \"Group # Bot\".")

        # Find the mod channel in each guild that this bot should report to
        for guild in self.guilds:
            for channel in guild.text_channels:
                if channel.name == f'group-{self.group_num}-mod':
                    self.mod_channels[guild.id] = channel

    async def on_raw_message_edit(self, payload):
        guild = client.get_guild(payload.guild_id)
        channel = guild.get_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)
        # handle adversarial attempts at hiding text via unicode
        message.content = uni2ascii(message.content)
        # treat all edited messages as new messages
        await self.on_message(message)

    async def on_message(self, message):
        '''
        This function is called whenever a message is sent in a channel that the bot can see (including DMs).
        Currently the bot is configured to only handle messages that are sent over DMs or in your group's "group-#" channel.
        '''
        # Ignore messages from the bot
        if message.author.id == self.user.id:
            return

        # handle adversarial attempts at hiding text via unicode
        message.content = uni2ascii(message.content)

        # Check if this message was sent in a server ("guild") or if it's a DM
        if message.guild:
            await self.handle_channel_message(message)
        else:
            await self.handle_dm(message)

    async def handle_dm(self, message):
        # Handle a help message
        if message.content == Report.HELP_KEYWORD:
            reply =  "Use the `report` command to begin the reporting process.\n"
            reply += "Use the `cancel` command to cancel the report process.\n"
            await message.channel.send(reply)
            return

        author_id = message.author.id
        responses = []

        # Only respond to messages if they're part of a reporting flow
        if author_id not in self.reports and not message.content.startswith(Report.START_KEYWORD):
            return

        # If we don't currently have an active report for this user, add one
        if author_id not in self.reports:
            self.reports[author_id] = Report(self)

        # Let the report class handle this message; forward all the messages it returns to uss
        responses = await self.reports[author_id].handle_message(message)
        for r in responses:
            await message.channel.send(r)

        # If the report is complete or cancelled, remove it from our map
        if self.reports[author_id].report_complete():
            self.reports.pop(author_id)

    async def on_raw_reaction_add(self, payload):
        if not str(self.mod_channels[payload.guild_id]) == 'group-14-mod':
            print("reaction sent but not in mod channel")
            return
        if payload.emoji.name == "👍":
            # TODO: delete message
            guild = client.get_guild(payload.guild_id)
            channel = guild.get_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)
            messageToDeleteId = message.content[message.content.rfind(':')+1:-3]
            print("should delete messageId: ", messageToDeleteId)

    async def handle_channel_message(self, message):
        # Only handle messages sent in the "group-#" channel
        if not message.channel.name == f'group-{self.group_num}':
            return

        # Forward the message to the mod channel
        mod_channel = self.mod_channels[message.guild.id]
        await mod_channel.send(f'Forwarded message:\n{message.author.name}: "{message.content}"')

        scores, flagged_scores = self.eval_text(message)
        await mod_channel.send(self.code_format("Scores in all measured categories: " + json.dumps(scores, indent=2)))
        if len(flagged_scores) > 0:
            await mod_channel.send(self.code_format(
                "We've flagged this message for you because it passed the acceptable threshold in these categories: "
                + json.dumps(flagged_scores, indent=2)))
            await mod_channel.send(self.code_format(
                "Please react to this message with 👍 if you'd like us to delete the message '"
                +message.content+"':"+str(message.id)))

    def eval_text(self, message):
        '''
        Given a message, forwards the message to Perspective and returns a dictionary of scores.
        '''
        PERSPECTIVE_URL = 'https://commentanalyzer.googleapis.com/v1alpha1/comments:analyze'

        url = PERSPECTIVE_URL + '?key=' + self.perspective_key
        data_dict = {
            'comment': {'text': message.content},
            'languages': ['en'],
            'requestedAttributes': {
                                    'SEVERE_TOXICITY': {}, 'PROFANITY': {},
                                    'IDENTITY_ATTACK': {}, 'THREAT': {},
                                    'TOXICITY': {}, 'INSULT': {}, 'INCOHERENT': {},
                                    'SPAM': {}, 'LIKELY_TO_REJECT':{}
                                },
            'doNotStore': True
        }
        response = requests.post(url, data=json.dumps(data_dict))
        response_dict = response.json()

        scores = {}
        flagged_scores = {}
        # TODO: Set to False
        use_dummy = False
        if use_dummy:
            pass
                # scores = {'SEVERE_TOXICITY': 4, 'PROFANITY': 5,
                #     'IDENTITY_ATTACK': 6, 'THREAT': 7,
                #     'TOXICITY': 8, 'FLIRTATION': 0, 'INCOHERENT'}
        else:
            for attr in response_dict["attributeScores"]:
                score = response_dict["attributeScores"][attr]["summaryScore"]["value"]
                scores[attr] = score
                if score >= PERSPECTIVE_SCORE_THRESHOLD:
                    flagged_scores[attr] = score

        print("scores for `{}`".format(message.content), scores)
        print("flagged scores for `{}`".format(message.content), flagged_scores)

        return scores, flagged_scores

    def code_format(self, text):
        return "```" + text + "```"


client = ModBot(perspective_key)
client.run(discord_token)
