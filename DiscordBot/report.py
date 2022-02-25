from enum import Enum, auto
import discord
import re

# USER REPORTING FLOW

class State(Enum):
    REPORT_START = auto()
    AWAITING_MESSAGE = auto()
    MESSAGE_IDENTIFIED = auto()
    REPORT_COMPLETE = auto()
    VIOLENCE = auto()
    SPAM = auto()
    HATE = auto()
    FALSE_INFO = auto()
    HARASSMENT = auto()
    SOCK_PUPPET = auto()
    BLOCK_USER = auto()

class Report:
    START_KEYWORD = "report"
    CANCEL_KEYWORD = "cancel"
    HELP_KEYWORD = "help"

    def __init__(self, client):
        self.state = State.REPORT_START
        self.client = client
        self.message = None

    async def generate_message_to_mods(self, reason_message, reason):
        mod_channel = self.client.mod_channels[self.message.guild.id]
        await mod_channel.send(f"""User-reported message:\n```{self.message.author.name}: "{self.message.content}```
Message was flagged by user {reason_message.author.name} for "{reason}".
Reported message sender id: {self.message.author.id}
Reported message id: {self.message.id}""")




    async def handle_message(self, message):
        '''
        This function makes up the meat of the user-side reporting flow. It defines how we transition between states and what
        prompts to offer at each of those states. You're welcome to change anything you want; this skeleton is just here to
        get you started and give you a model for working with Discord.
        '''

        if message.content == self.CANCEL_KEYWORD:
            self.state = State.REPORT_COMPLETE
            return ["Report cancelled."]

        if self.state == State.REPORT_START:
            reply =  "Thank you for starting the reporting process. "
            reply += "Say `help` at any time for more information.\n\n"
            reply += "Please copy paste the link to the message you want to report.\n"
            reply += "You can obtain this link by right-clicking the message and clicking `Copy Message Link`."
            self.state = State.AWAITING_MESSAGE
            return [reply]

        if self.state == State.AWAITING_MESSAGE:
            # Parse out the three ID strings from the message link
            m = re.search('/(\d+)/(\d+)/(\d+)', message.content)
            if not m:
                return ["I'm sorry, I couldn't read that link. Please try again or say `cancel` to cancel."]
            guild = self.client.get_guild(int(m.group(1)))
            if not guild:
                return ["I cannot accept reports of messages from guilds that I'm not in. Please have the guild owner add me to the guild and try again."]
            channel = guild.get_channel(int(m.group(2)))
            if not channel:
                return ["It seems this channel was deleted or never existed. Please try again or say `cancel` to cancel."]
            try:
                message = await channel.fetch_message(int(m.group(3)))
            except discord.errors.NotFound:
                return ["It seems this message was deleted or never existed. Please try again or say `cancel` to cancel."]

            # Here we've found the message - it's up to you to decide what to do next!
            self.state = State.MESSAGE_IDENTIFIED
            # TODO: Prompt for more information
            self.message = message
            return ["I found this message:", "```" + message.author.name + ": " + message.content + "```", \
                    "Please select a problem with this message by typing the number next to the appropriate reason:", \
                    "1: Violence or danger", "2: Spam", "3: Hate speech or symbols", "4: False information", "5: Harrassment"]


        if self.state == State.MESSAGE_IDENTIFIED:
            # TODO: Do whatever response needed
            if message.content == "1":
                self.state = State.VIOLENCE
                return ["Who is the threat towards?", "1: You", "2: Someone else"]
            elif message.content == "2":
                self.state = State.SPAM
                return ["How is this message spam?", "1: The user is fake", "2: Includes a link to a potentially harmful, malicious, or phishing site", "3: It's something else"]
            elif message.content == "3":
                self.state = State.HATE
                return ["What kind of hate speech is this?", "1: Race or ethnicity", "2: Sex, gender, or sexual orientation", "3: Religion", "4: National origin", "5: Disability or disease"]
            elif message.content == "4":
                self.state = State.FALSE_INFO
                return ["What's this message misleading about?", "1: Politics", "2: Health", "3: Something else"]
            elif message.content == "5":
                self.state = State.HARASSMENT
                return ["How is this message harrassment?", "1: Degrading or shaming someone", "2: Repeatedly contacting a person or group that doesn't want contact", "3: Calling for the harm of someone"]
            else:
                return ["I'm sorry, that's not one of the choices. Please try again or say `cancel` to cancel."]
        if self.state == State.VIOLENCE:
            choice_to_text = {"1": "You", "2": "Someone else"}
            if message.content not in choice_to_text:
                return ["I'm sorry, that's not one of the choices. Please try again or say `cancel` to cancel."]
            else:
                await self.generate_message_to_mods(message, f'violence or danger towards {choice_to_text[message.content]}')
                self.state = State.BLOCK_USER
                return [
                    "Thanks for letting us know. We'll use this information to alert our content moderation team and improve our processes. The message will be reviewed, and the user and/or message will be removed if appropriate.",
                    "Would you also like to block or mute this user?",
                    "1: Block, 2: Mute, 3: None"
                ]
        if self.state == State.SPAM:
            choice_to_text = {
                "1": "The user is fake",
                "2": "Includes a link to a potentially harmful, malicious, or phishing site",
                "3": "It's something else",
            }
            if message.content not in choice_to_text:
                return ["I'm sorry, that's not one of the choices. Please try again or say `cancel` to cancel."]
            else:
                await self.generate_message_to_mods(message, f'spam: {choice_to_text[message.content]}')
                self.state = State.BLOCK_USER
                return [
                    "Thanks for letting us know. We'll use this information to alert our content moderation team and improve our processes. The message will be reviewed, and the user and/or message will be removed if appropriate.",
                    "Would you also like to block or mute this user?",
                    "1: Block, 2: Mute, 3: None"
                ]
        if self.state == State.HATE:
            choice_to_text = {
                "1": "Race or ethnicity",
                "2": "Sex, gender, or sexual orientation",
                "3": "Religion",
                "4": "National origin",
                "5": "Disability or disease",
            }
            if message.content not in choice_to_text:
                return ["I'm sorry, that's not one of the choices. Please try again or say `cancel` to cancel."]
            else:
                await self.generate_message_to_mods(message, f'hate speech or symbols relating to {choice_to_text[message.content]}')
                self.state = State.BLOCK_USER
                return [
                    "Thanks for letting us know. We'll use this information to alert our content moderation team and improve our processes. The message will be reviewed, and the user and/or message will be removed if appropriate.",
                    "Would you also like to block or mute this user?",
                    "1: Block, 2: Mute, 3: None"
                ]
        if self.state == State.FALSE_INFO:
            choice_to_text = {
                "1": "Politics",
                "2": "Health",
                "3": "Something else",
            }
            if message.content not in choice_to_text:
                return ["I'm sorry, that's not one of the choices. Please try again or say `cancel` to cancel."]
            else:
                await self.generate_message_to_mods(message, f'false information about {choice_to_text[message.content]}')
                self.state = State.SOCK_PUPPET
                return ["Do you suspect that this account is a bot or sock puppet user?", "1: yes", "2: no"]

        if self.state == State.HARASSMENT:
            choice_to_text = {
                "1": "Degrading or shaming someone",
                "2": "Repeatedly contacting a person or group that doesn't want contact",
                "3": "Encourages the harm of someone",
            }
            if message.content not in choice_to_text:
                return ["I'm sorry, that's not one of the choices. Please try again or say `cancel` to cancel."]
            else:
                await self.generate_message_to_mods(message, f'harrassment: {choice_to_text[message.content]}')
                self.state = State.SOCK_PUPPET
                return ["Do you suspect that this account is a bot or sock puppet user?", "1: yes", "2: no"]
        if self.state == State.SOCK_PUPPET:
            if message.content not in ["1", "2"]:
                return ["I'm sorry, that's not one of the choices. Please try again or say `cancel` to cancel."]
            else:
                if message.content == "1":
                    mod_channel = self.client.mod_channels[self.message.guild.id]
                    await mod_channel.send(f"{self.message.author} was also flagged as a possible bot or sock puppet account")
                self.state = State.BLOCK_USER
                return [
                    "Thanks for letting us know. We'll use this information to alert our content moderation team and improve our processes. The message will be reviewed, and the user and/or message will be removed if appropriate.",
                    "Would you also like to block or mute this user?",
                    "1: Block, 2: Mute, 3: None"
                ]
        if self.state == State.BLOCK_USER:
            if message.content not in ["1", "2", "3"]:
                return ["I'm sorry, that's not one of the choices. Please try again or say `cancel` to cancel."]
            else:
                if message.content == "1":
                    self.state = State.REPORT_COMPLETE
                    return [f"You blocked user {self.message.author.name}."]
                elif message.content == "2":
                    self.state = State.REPORT_COMPLETE
                    return [f"You muted user {self.message.author.name}."]
                self.state = State.REPORT_COMPLETE


        return []

    def report_complete(self):
        return self.state == State.REPORT_COMPLETE
