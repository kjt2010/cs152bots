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
import time
import asyncio
import csv
import pandas as pd
from datetime import datetime, timedelta
from matplotlib import pyplot as plt
from matplotlib import dates as mpl_dates
import networkx as nx
from deep_translator import GoogleTranslator
import dataframe_image as dfi
from pandas.plotting import table


PERSPECTIVE_SCORE_THRESHOLD = 0.80
PERSPECTIVE_SCORE_THRESHOLD_BY_ATTR = {
    'SEVERE_TOXICITY': 0.51, 'PROFANITY': 0.80,
    'IDENTITY_ATTACK': 0.51, 'THREAT': 0.51,
    'TOXICITY': 0.70, 'INSULT': 0.70, 'INCOHERENT': 0.9,
    'SPAM': 0.9,
}
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
        self.general_channel = None
        self.reports = {} # Map from user IDs to the state of their report
        self.perspective_key = key
        self.deleteMap = {}

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
                if channel.name == f'group-{self.group_num}':
                    self.general_channel = channel

    async def on_raw_message_edit(self, payload):
        guild = client.get_guild(payload.guild_id)
        channel = guild.get_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)
        # handle adversarial attempts at hiding text via unicode
        message.content = uni2ascii(message.content)
        # translate all messages in other languages to english
        message.content = GoogleTranslator(source='auto', target='en').translate(message.content)
        # treat all edited messages as new messages
        await self.on_message(message)

    async def on_message(self, message):
        '''
        This function is called whenever a message is sent in a channel that the bot can see (including DMs).
        Currently the bot is configured to only handle messages that are sent over DMs or in your group's "group-#" channel.
        '''
        # Ignore messages from the bot unless it's a forwarded message
        if message.author.id == self.user.id and not message.content.startswith("User-reported message"):
            return


        # handle adversarial attempts at hiding text via unicode
        message.content = uni2ascii(message.content)
        # translate all messages in other languages to english
        message.content = GoogleTranslator(source='auto', target='en').translate(message.content)


        # Create a map of messageId -> message.delete() function to use if moderator reacts to bot
        # self.deleteMap[str(message.id)] = message.delete
        self.deleteMap[str(message.id)] = message.add_reaction

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

    def generate_time_plot(self, authorToGraph, user):
        with open("./time_data.csv") as f:
            data = [line.split('\t') for line in f]
            times = []
            for row in data:
                if len(row)>1 and str(row[1]) == str(authorToGraph):
                    message_id, message_author_id, message_author_name, message_content, message_timestamp, message_mentions, count, temp = row
                    times.append(datetime.strptime(message_timestamp[:-7], '%Y-%m-%d %H:%M:%S')) #cutting out the milliseconds
                    # plt.plot_date(time, count)
        plt.hist(times)
        plt.gcf().autofmt_xdate()
        date_format = mpl_dates.DateFormatter('%D %H:%M:%S')
        plt.gca().xaxis.set_major_formatter(date_format)
        plt.title("User "+ str(user)+"'s messages over time")
        plt.savefig(fname='timePlot')

    def generate_network_graph(self, user):
        data_panda = pd.read_csv("./network_data.csv", sep='\t',lineterminator='\n')
        data_panda.dropna( #drop blank rows
                axis = 0,
                how = 'all',
                thresh = None,
                subset = None,
                inplace = True,
        )
        G = nx.from_pandas_edgelist(data_panda, #Create a directed graph
                    source = 'message_author_name',
                    target = 'message_mentions',
                    edge_attr = True,
                    create_using = nx.DiGraph()
        )
        color_map = []
        size_map = []
        for node in G:
            if node == user.name: color_map.append('red')
            else: color_map.append('green')
            size_map.append(500)
        nx.draw_networkx(G,
            node_color = color_map,
            node_size = size_map,
            node_shape = "8",#can choose s,o,^,>,v,<,d,p,h,8...o is default
            alpha = 0.75,
            font_size = 10,
            font_color = "black",
            font_weight = "bold",
            edge_color = "skyblue",
            style = "solid",
            width = 5,
            label = "User Mentions",
            pos = nx.spring_layout(G, iterations = 1000),
            arrows = True, with_labels = True)
        plt.title("User "+ str(user)+"'s network")
        plt.savefig(fname='networkPlot')    

    def generate_freq_table(self, flagged_message):
        f = open("./time_data.csv")
        csv_f = csv.reader(f)
        message_of_interest = {}
        author_count = {}
        with open("./time_data.csv") as f:
            data = [line.split('\t') for line in f]
            for row in data:
                if len(row)>1 and str(row[3]) == str(flagged_message.content):
                    message_id, message_author_id, message_author_name, message_content, message_timestamp, message_mentions, count, temp = row
                    if message_author_name not in author_count:
                        author_count[message_author_name] = 1
                    else:
                        author_count[message_author_name] += 1 
                    message_of_interest[flagged_message.content] = author_count
            print("Check dictionary: ", message_of_interest) 
            freq_data = pd.DataFrame(message_of_interest)
            dfi.export(freq_data,"table.png") 
      
    async def on_raw_reaction_add(self, payload):
        guild = client.get_guild(payload.guild_id)
        channel = guild.get_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)
        if str(channel) != 'group-14-mod':
            # reaction sent but not in mod channel
            return
        id_start_i = message.content.rfind(":") + 1
        ID_LEN = 18
        author_id = message.content[id_start_i: id_start_i + ID_LEN]
        flagged_message_id = message.content[id_start_i + ID_LEN: id_start_i + 2 * ID_LEN]

        if payload.emoji.name == "👍":
            messageToDeleteId = flagged_message_id
            print("Deleting message: ", messageToDeleteId)
            await self.deleteMap[str(messageToDeleteId)]("🗑️")
        if payload.emoji.name == "✅":
            authorToGraph = author_id
            messageId = flagged_message_id
            flagged_message = await self.general_channel.fetch_message(messageId)
            user = await client.fetch_user(int(authorToGraph))
            # graphing time series data
            self.generate_time_plot(authorToGraph, user)
            await channel.send(file=discord.File('timePlot.png'))
            plt.clf()  
            # graphing network data
            self.generate_network_graph(user)
            await channel.send(file=discord.File('networkPlot.png'))
            plt.clf()
            # Generate frequency table
            self.generate_freq_table(flagged_message)
            await channel.send(file=discord.File('table.png'))

        if payload.emoji.name == "❌":
            userToSuspend = author_id
            user = await client.fetch_user(int(userToSuspend))
            channel = self.mod_channels[payload.guild_id]
            await channel.send(f"User {user.name} has been suspended.")
        if payload.emoji.name == "🗑️":
            userToSuspend = author_id
            user = await client.fetch_user(int(userToSuspend))
            channel = self.mod_channels[payload.guild_id]
            await channel.send(f"User {user.name} has been deleted.")

    async def handle_channel_message(self, message):
        # Only handle messages sent in the "group-#" channel

        # record message in csv file
        f = open('./time_data.csv', 'a+', newline='')
        row = [str(message.id), str(message.author.id), message.author.name, message.content, str(message.created_at), str([m.name for m in message.mentions]), "1"]
        for el in row:
            f.write(el + '\t')
        f.write('\n')
        f.close()

        # record messages with mentions in csv file
        write_obj =  open('./network_data.csv','a+',newline='')
        for m in message.mentions:
            row = [str(message.id), str(message.author.id), message.author.name, message.content, str(message.created_at), str(m.name), "1"]#tried to use r.find("'")... on m.name to clean user mention display, but no luck
            if row[5] != "":
                for el in row:
                    write_obj.write(el + '\t')
                write_obj.write('\n')
        write_obj.close()


        mod_channel = self.mod_channels[message.guild.id]
        if message.channel == mod_channel and message.content.startswith("User-reported message"):
            user_id_start = message.content.rfind("Author id: ") + len("Author id: ")
            user_id = message.content[user_id_start: user_id_start + 18]
            message_id_start = message.content.rfind("Message id: ") + len("Message id: ")
            message_id = message.content[message_id_start: message_id_start + 18]
            delete_message_string_suffix = f"react to this with 👍 to delete the message."
            suspend_user_string_suffix = f"react to this with ❌ to suspend the user's account."
            remove_user_string_suffix = f"react to this with 🗑️ to remove the user's account."
            id_suffix = self.hidden_format(f"id:{user_id}{message_id}")


            topic = message.content[message.content.rfind("for") + 6:]
            topic_end = topic.find(".")
            topic = topic[:topic_end]
            if topic.startswith('"violence'):
                await mod_channel.send(
                    f"If the reported message glorifies violence, " + delete_message_string_suffix + '\n' +
                    "If the reported message threatens violence against an individual or a group of people, " + suspend_user_string_suffix + '\n' +
                    id_suffix
                )

            elif topic.startswith('"spam: Includes a link'):
                await mod_channel.send("If the reported message deceptively or misleadingly directs users to a harmful site, " + delete_message_string_suffix + '\n' + id_suffix)
            elif topic.startswith('"spam: The user is fake'):
                await mod_channel.send("If the reported message's sender impersonates individuals or groups and intends to deceive others, " + remove_user_string_suffix + '\n' + id_suffix)

            elif topic.startswith('"hate'):
                await mod_channel.send("If the reported message promotes violence against, threatens, harasses, or promotes terrorism or violent extremism other people on the basis of race, ethnicity, sexual orientation, gender, religion, national origin, disability, or disease, " + suspend_user_string_suffix + '\n' + id_suffix)

            elif topic.startswith('"false info about Politics'):
                await mod_channel.send(
                    "If the reported message is manipulating or interfering in elections or other civic processes (This includes posting or sharing content that may suppress participation or mislead people about when, where, or how to participate in a civic process 's sender impersonates individuals or groups and intends to deceive others), " + delete_message_string_suffix + '\n' +
                    "If you suspect that this account is a bot or a sock puppet user, " + remove_user_string_suffix + '\n' +
                    id_suffix
                )

            elif topic.startswith('"false info'):
                await mod_channel.send(
                    "If the reported message is likely to cause harm, "+ delete_message_string_suffix + '\n' +
                    "If you suspect that this account is a bot or a sock puppet user, " + remove_user_string_suffix + '\n' +
                    id_suffix
                )
            elif topic.startswith('"harrassment'):
                if topic.startswith('"harrassment: Degrading'):
                    await mod_channel.send("If the reported message targets a individual or group by with dehumanizing statements, calls for segregation or exclusion, or statements of inferiority, " + suspend_user_string_suffix + '\n' + id_suffix)
                elif topic.startswith('"harrassment: Repeatedly'):
                    await mod_channel.send("If there a pattern of actions or previous reports by the reporter, " + suspend_user_string_suffix + '\n' + id_suffix)
                elif topic.startswith('"harrassment: Encourages'):
                    await mod_channel.send("If the reported message includes the targeted harassment of someone, or incites other people to do so (this includes wishing or hoping that someone experiences physical harm), " + suspend_user_string_suffix + '\n' +  id_suffix)
                await mod_channel.send("If you suspect that this account is a bot or a sock puppet user, " + remove_user_string_suffix + '\n' + id_suffix)




        if not message.channel.name == f'group-{self.group_num}':
            return

        # Forward the message to the mod channel

        # handle adversarial attempts at hiding text via unicode
        message.content = uni2ascii(message.content)
        # translate all messages in other languages to english
        message.content = GoogleTranslator(source='auto', target='en').translate(message.content)

        scores, flagged_scores = self.eval_text(message)
        # await mod_channel.send(self.code_format("Scores in all measured categories: " + json.dumps(scores, indent=2)))
        if len(flagged_scores) > 0:

            await mod_channel.send(
                f'**Flagged message**:\n{message.author.name}: "{message.content}"' + "\n" +
                f'**Flagged categories**:' + self.code_format(json.dumps(flagged_scores, indent=2)) + "\n" +
                self.bold_format("To delete the flagged message") + ", react to this with 👍 \n" +
                self.bold_format("To suspend the user who sent the message") + ", react to this with ❌ \n" +
                self.bold_format("To see an analysis of the message and the author's messaging history") + ", react to this with ✅ \n" + self.hidden_format("id:"+ str(message.author.id) + str(message.id))
            )

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
                                    'SPAM': {},
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
                if score >= PERSPECTIVE_SCORE_THRESHOLD_BY_ATTR[attr]:
                    flagged_scores[attr] = score

        print("scores for `{}`".format(message.content), scores)
        print("flagged scores for `{}`".format(message.content), flagged_scores)

        return scores, flagged_scores

    def code_format(self, text):
        return "```" + text + "```"
    def hidden_format(self, text):
        return "||" + text + "||"
    def bold_format(self, text):
        return "**" + text + "**"
    def italic_format(self, text):
        return "*"+text+"*"


client = ModBot(perspective_key)
client.run(discord_token)
