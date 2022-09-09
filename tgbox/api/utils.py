"""Module with all API utils."""

from typing import (
    BinaryIO, Optional,
    Union, AsyncGenerator
)
from os import PathLike
from dataclasses import dataclass

from telethon.tl.custom.file import File
from telethon.sessions import StringSession

from telethon.tl.types import Photo, Document
from telethon.tl.types.auth import SentCode

from telethon import TelegramClient as TTelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.tl.functions.auth import ResendCodeRequest

try:
    from regex import search as re_search
except ImportError:
    from re import search as re_search

from ..defaults import VERSION
from ..tools import anext, SearchFilter
from ..fastelethon import download_file

__all__ = [
    'search_generator',
    'DirectoryRoot',
    'PreparedFile',
    'TelegramClient',
]
class TelegramClient(TTelegramClient):
    """
    A little extend to the ``telethon.TelegramClient``.

    This class inherits Telethon's TelegramClient and support
    all features that has ``telethon.TelegramClient``.

    Typical usage:

    .. code-block:: python

        from asyncio import run as asyncio_run
        from tgbox.api import TelegramClient, make_remotebox
        from getpass import getpass # For hidden input

        PHONE_NUMBER = '+10000000000' # Your phone number
        API_ID = 1234567 # Your API_ID: https://my.telegram.org
        API_HASH = '00000000000000000000000000000000' # Your API_HASH

        async def main():
            tc = TelegramClient(
                phone_number = PHONE_NUMBER,
                api_id = API_ID,
                api_hash = API_HASH
            )
            await tc.connect()
            await tc.send_code()

            await tc.log_in(
                code = int(input('Code: ')),
                password = getpass('Pass: ')
            )
            erb = await make_remotebox(tc)

        asyncio_run(main())
    """
    def __init__(
            self, api_id: int, api_hash: str,
            phone_number: Optional[str] = None,
            session: Optional[Union[str, StringSession]] = None):
        """
        Arguments:
            api_id (``int``):
                API_ID from https://my.telegram.org.

            api_hash (``int``):
                API_HASH from https://my.telegram.org.

            phone_number (``str``, optional):
                Phone number linked to your Telegram
                account. You may want to specify it
                to recieve log-in code. You should
                specify it if ``session`` is ``None``.

            session (``str``, ``StringSession``, optional):
                ``StringSession`` that give access to
                your Telegram account. You can get it
                after connecting and signing in via
                ``TelegramClient.session.save()`` method.

            You should specify at least ``session`` or ``phone_number``.
        """
        if not session and not phone_number:
            raise ValueError(
                'You should specify at least ``session`` or ``phone_number``.'
            )
        super().__init__(
            StringSession(session),
            api_id, api_hash
        )
        self.__version__ = VERSION
        self._api_id, self._api_hash = api_id, api_hash
        self._phone_number = phone_number

    async def send_code(self, force_sms: Optional[bool]=False) -> SentCode:
        """
        Sends the Telegram code needed to login to the given phone number.

        Arguments:
            force_sms (``bool``, optional):
                Whether to force sending as SMS.
        """
        return await self.send_code_request(
            self._phone_number, force_sms=force_sms
        )
    async def log_in(
            self, password: Optional[str] = None,
            code: Optional[Union[int,str]] = None) -> None:
        """
        Logs in to Telegram to an existing user account.
        You should only use this if you are not signed in yet.

        Arguments:
            password (``str``, optional):
                Your 2FA password. You can ignore
                this if you don't enabled it yet.

            code (``int``, optional):
                The code that Telegram sent you after calling
                ``TelegramClient.send_code()`` method.
        """
        if not await self.is_user_authorized():
            try:
                await self.sign_in(self._phone_number, code)
            except SessionPasswordNeededError:
                await self.sign_in(password=password)

    async def resend_code(self, sent_code: SentCode) -> SentCode:
        """
        Will send you login code again. This can be used to
        force Telegram send you SMS or Call to dictate code.

        Arguments:
            sent_code (``SentCode``):
                Result of the ``tc.send_code`` or
                result of the ``tc.resend_code`` method.

        Example:

        .. code-block:: python

            tc = tgbox.api.TelegramClient(...)
            sent_code = await tc.send_code()
            sent_code = await tc.resend_code(sent_code)
        """
        return await self(ResendCodeRequest(
            self._phone_number, sent_code.phone_code_hash)
        )
@dataclass
class PreparedFile:
    """
    This dataclass store data needed for upload
    by ``DecryptedRemoteBox.push_file`` in future.

    Usually it's only for internal use.
    """
    dlb: 'tgbox.api.local.DecryptedLocalBox'
    file: BinaryIO
    filekey: 'tgbox.keys.FileKey'
    filesize: int
    filepath: PathLike
    filesalt: bytes
    metadata: bytes
    imported: bool

    def set_file_id(self, id: int):
        """You should set ID after pushing to remote"""
        self.file_id = id

    def set_upload_time(self, upload_time: int):
        """You should set time after pushing to remote"""
        self.upload_time = upload_time

class DirectoryRoot:
    """
    Type used to specify that you want to
    access absolute local directory root.

    This class doesn't have any methods,
    please use it only for ``lbd.iterdir``
    """

# TODO: Test with imported file
# TODO: Improve SearchFilter
async def search_generator(
        sf: SearchFilter, it_messages: Optional[AsyncGenerator] = None,
        lb: Optional['tgbox.api.local.DecryptedLocalBox'] = None) -> AsyncGenerator:
    """
    Generator used to search for files in dlb and rb. It's
    only for internal use, and you shouldn't use it in your
    own projects.

    If file is imported from other RemoteBox and was exported
    to your LocalBox, then you can specify ``dlb`` as ``lb``. AsyncGenerator
    will try to get ``FileKey`` and decrypt ``EncryptedRemoteBoxFile``.
    Otherwise imported file will be ignored.
    """
    in_func = re_search if sf.in_filters['re'] else lambda p,s: p in s

    if it_messages:
        iter_from = it_messages
    else:
        min_id = sf.in_filters['min_id'][-1] if sf.in_filters['min_id'] else None
        max_id = sf.in_filters['max_id'][-1] if sf.in_filters['max_id'] else None
        iter_from = lb.files(min_id=min_id, max_id=max_id)

    if not iter_from:
        raise ValueError('At least it_messages or lb must be specified.')

    async for file in iter_from:
        if hasattr(file, '_message'): # *RemoteBoxFile
            file_size = file.file_size
        elif hasattr(file, '_tgbox_db'): # *LocalBoxFile
            file_size = file.size
        else:
            continue

        # We will use it as flags, the first
        # is for 'include', the second is for
        # 'exclude'. Both should be True to
        # match SearchFilter filters.
        yield_result = [True, True]

        for indx, filter in enumerate((sf.in_filters, sf.ex_filters)):
            if filter['exported']:
                if bool(file.exported) != bool(filter['exported']):
                    if indx == 0: # O is Include
                        yield_result[indx] = False
                        break

                elif bool(file.exported) == bool(filter['exported']):
                    if indx == 1: # 1 is Exclude
                        yield_result[indx] = False
                        break

            for mime in filter['mime']:
                if in_func(mime, file.mime):
                    if indx == 1:
                        yield_result[indx] = False
                    break
            else:
                if filter['mime']:
                    if indx == 0:
                        yield_result[indx] = False
                        break

            if filter['min_time']:
                if file.upload_time < filter['min_time'][-1]:
                    if indx == 0:
                        yield_result[indx] = False
                        break

                elif file.upload_time >= filter['min_time'][-1]:
                    if indx == 1:
                        yield_result[indx] = False
                        break

            if filter['max_time']:
                if file.upload_time > filter['max_time'][-1]:
                    if indx == 0:
                        yield_result[indx] = False
                        break

                elif file.upload_time <= filter['max_time'][-1]:
                    if indx == 1:
                        yield_result[indx] = False
                        break

            if filter['min_size']:
                if file_size < filter['min_size'][-1]:
                    if indx == 0:
                        yield_result[indx] = False
                        break

                elif file_size >= filter['min_size'][-1]:
                    if indx == 1:
                        yield_result[indx] = False
                        break

            if filter['max_size']:
                if file_size > filter['max_size'][-1]:
                    if indx == 0:
                        yield_result[indx] = False
                        break

                elif file_size <= filter['max_size'][-1]:
                    if indx == 1:
                        yield_result[indx] = False
                        break

            if filter['min_id']:
                if file.id < filter['min_id'][-1]:
                    if indx == 0:
                        yield_result[indx] = False
                        break

                elif file.id >= filter['min_id'][-1]:
                    if indx == 1:
                        yield_result[indx] = False
                        break

            if filter['max_id']:
                if file.id > filter['max_id'][-1]:
                    if indx == 0:
                        yield_result[indx] = False
                        break

                elif file.id <= filter['max_id'][-1]:
                    if indx == 1:
                        yield_result[indx] = False
                        break

            for id in filter['id']:
                if file.id == id:
                    if indx == 1:
                        yield_result[indx] = False
                    break
            else:
                if filter['id']:
                    if indx == 0:
                        yield_result[indx] = False
                        break

            if hasattr(file, '_cattrs'):
                for cattr in filter['cattrs']:
                    for k,v in cattr.items():
                        if k in file.cattrs:
                            if in_func(v, file.cattrs[k]):
                                if indx == 1:
                                    yield_result[indx] = False
                                break
                    else:
                        if filter['cattrs']:
                            if indx == 0:
                                yield_result[indx] = False
                                break

            for file_path in filter['file_path']:
                if in_func(str(file_path), str(file.file_path)):
                    if indx == 1:
                        yield_result[indx] = False
                    break
            else:
                if filter['file_path']:
                    if indx == 0:
                        yield_result[indx] = False
                        break

            for file_name in filter['file_name']:
                if in_func(file_name, file.file_name):
                    if indx == 1:
                        yield_result[indx] = False
                    break
            else:
                if filter['file_name']:
                    if indx == 0:
                        yield_result[indx] = False
                        break

            for file_salt in filter['file_salt']:
                if in_func(file_salt, file.file_salt):
                    if indx == 1:
                        yield_result[indx] = False
                    break
            else:
                if filter['file_salt']:
                    if indx == 0:
                        yield_result[indx] = False
                        break

            for verbyte in filter['verbyte']:
                if verbyte == file.verbyte:
                    if indx == 1:
                        yield_result[indx] = False
                    break
            else:
                if filter['verbyte']:
                    if indx == 0:
                        yield_result[indx] = False
                        break

        if all(yield_result):
            yield file
        else:
            continue

class _TelegramVirtualFile:
    """
    We use this class for re-upload to RemoteBox
    files that already was uploaded to any other
    Telegram chat. That's only for internal use.
    """
    def __init__(
            self, document: Union[Photo, Document],
            session: StringSession,
            api_id: int, api_hash: str):

        self.downloader = None
        self.document = document

        self.tc = TelegramClient(
            session=session,
            api_id=api_id,
            api_hash=api_hash
        )
        self.tc = self.tc.connect()
        self._client_initialized = False

        file = File(document)

        self.name = file.name
        self.size = file.size
        self.mime = file.mime_type

        self.duration = file.duration\
            if file.duration else 0

    async def get_preview(self, quality: int=1) -> bytes:
        if not self._client_initialized:
            self.tc = await self.tc # connect
            self._client_initialized = True

        if hasattr(self.document,'sizes')\
            and not self.document.sizes:
                return b''

        if hasattr(self.document,'thumbs')\
            and not self.document.thumbs:
                return b''

        return await self.tc.download_media(
            message = self.document,
            thumb = quality, file = bytes
        )
    async def read(self, size: int) -> bytes:
        if not self._client_initialized:
            self.tc = await self.tc
            self._client_initialized = True

        if not self.downloader:
            self.downloader = download_file(
                self.tc, self.document
            )
        chunk = await anext(self.downloader)
        return chunk