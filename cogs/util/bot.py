import traceback
import datetime
import aiohttp
import logging
import sys
import re

from discord.ext import commands
import ruamel.yaml as yaml
import discord


class HelperBodge():
    def __init__(self, data):
        self.data = data
    def format(self, arg):
        return self.data.format(arg.replace('@', '@\u200b'))


class VEXBot(commands.AutoShardedBot):
    class SilentCheckFailure(commands.CheckFailure): pass

    def __init__(self, log_file=None, *args, **kwargs):
        self.debug = False
        self.config = {}
        with open('config/config.yml', 'r') as f:
            self.config = yaml.load(f, Loader=yaml.Loader)

        logging.basicConfig(level=logging.INFO, format='[%(name)s %(levelname)s] %(message)s')
        self.logger = logging.getLogger('bot')

        super().__init__(
            command_prefix='!',
            command_not_found=HelperBodge('No command called `{}` found.'),
            guild_subscriptions=False,
            *args,
            **kwargs
        )
        self.session = aiohttp.ClientSession(loop=self.loop)

    async def get_prefix(self, message):
        if message.guild is None:
            return [self.config['prefix'][i] for i in self.config['prefix']]
        if message.guild.id not in self.config['prefix']:
            return self.config['prefix']['default']
        return self.config['prefix'][message.guild.id]

    async def notify_devs(self, lines, message: discord.Message = None):
        embed = discord.Embed(colour=0xFF0000, title='An error occurred \N{FROWNING FACE WITH OPEN MOUTH}')

        if message is not None:
            if len(message.content) > 400:
                url = await self.uploader_client.upload(message.content, 'Message triggering error')
                embed.add_field(name='Command', value=url, inline=False)
            else:
                embed.add_field(name='Command', value='```\n{}\n```'.format(message.content), inline=False)
            embed.set_author(name=message.author, icon_url=message.author.avatar_url_as(format='png'))

        embed.set_footer(text='{} UTC'.format(datetime.datetime.utcnow()))

        error_message = ''.join(lines)
        print(error_message)
        if len(error_message) > 1000:
            error_message = error_message[-1000:]
        embed.add_field(name='Error', value=f'```py\n{error_message}\n```', inline=False)

        # loop through all developers, send the embed
        for dev in self.config.get('ids', {}).get('developers', []):
            dev = self.get_user(dev)

            if dev is None:
                self.logger.warning('Could not get developer with an ID of {0.id}, skipping.'.format(dev))
                continue
            try:
                await dev.send(embed=embed)
            except Exception as e:
                self.logger.error('Couldn\'t send error embed to developer {0.id}. {1}'
                                  .format(dev, type(e).__name__ + ': ' + str(e)))

    async def on_command_error(self, ctx: commands.Context, exception: Exception):
        if isinstance(exception, commands.CommandInvokeError):
            # all exceptions are wrapped in CommandInvokeError if they are not a subclass of CommandError
            # you can access the original exception with .original
            original = exception.original
            if isinstance(original, discord.Forbidden):
                # permissions error
                try:
                    await ctx.send('Permissions error: `{}`'.format(exception))
                except discord.Forbidden:
                    # we can't send messages in that channel
                    pass
            elif isinstance(original, discord.HTTPException) and original.status == 400:
                try: await ctx.send('Congratulations! I can\'t send that message.')
                except discord.Forbidden: pass

            if not (isinstance(original, discord.HTTPException) and original.status == 400):
                # Print to log then notify developers
                lines = traceback.format_exception(type(exception),
                                                exception,
                                                exception.__traceback__)

                self.logger.error(''.join(lines))
                await self.notify_devs(lines, ctx.message)

        elif isinstance(exception, commands.CheckFailure):
            if not isinstance(exception, self.SilentCheckFailure):
                self.logger.error(ctx.channel)
                await ctx.send('You can\'t do that.')
        elif isinstance(exception, commands.CommandNotFound):
            pass
        elif isinstance(exception, commands.UserInputError):
            error = ' '.join(exception.args)
            error_data = re.findall('Converting to \"(.*)\" failed for parameter \"(.*)\"\.', error)
            if not error_data:
                await ctx.send('Error: {}'.format(' '.join(exception.args)))
            else:
                await ctx.send('Failed to convert `{1}` to `{0}`'.format(*error_data[0]))
        else:
            info = traceback.format_exception(type(exception), exception, exception.__traceback__, chain=False)
            self.logger.error('Unhandled command exception - {}'.format(''.join(info)))
            await self.notify_devs(info, ctx.message)

    async def on_error(self, event_method, *args, **kwargs):
        info = sys.exc_info()
        await self.notify_devs(traceback.format_exception(*info, chain=False))

    async def on_ready(self):
        self.logger.info(f'Connected to Discord as {self.user}')
        self.logger.info(f'Guilds  : {len(self.guilds)}')
        self.logger.info(f'Users   : {len(set(self.get_all_members()))}')
        self.logger.info(f'Channels: {len(list(self.get_all_channels()))}')

    def run(self):
        debug = any('debug' in arg.lower() for arg in sys.argv) or self.config.get('debug_mode', False)

        if debug:
            # if debugging is enabled, use the debug subconfiguration (if it exists)
            if 'debug' in self.config:
                self.config = {**self.config, **self.config['debug']}
            self.logger.info('Debug mode active...')
            self.debug = True

        token_file = self.config['token_file']
        with open(token_file) as f:
            token = f.read().split('\n')[0].strip()

        cogs = self.config.get('cogs', [])

        for cog in cogs:
            try:
                self.load_extension(cog)
            except Exception:
                self.logger.exception('Failed to load cog {}.'.format(cog))
            else:
                self.logger.info('Loaded cog {}.'.format(cog))

        self.logger.info('Loaded {} cogs'.format(len(self.cogs)))

        super().run(token)