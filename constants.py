"""Shared constants for the movenotes Joplin import/export scripts."""

#
# MIT License
#
# https://opensource.org/licenses/MIT
#
# Copyright 2020 Rene Sugar
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from enum import IntEnum

# Name and fixed id of the default notebook created when the database
# contains no folders of its own.
NOTES_FOLDER_NAME = "Notes"
NOTES_FOLDER_UUID = "2e7ca3c0de554a7b870630ea2848e731"
NOTES_UNTITLED = "Untitled"


class JoplinType(IntEnum):
    """Item types used in the ``type_`` property of Joplin RAW files.

    See https://joplinapp.org/help/api/references/rest_api/#item-type-ids
    """

    NOTE = 1
    FOLDER = 2
    SETTING = 3
    RESOURCE = 4
    TAG = 5
    NOTE_TAG = 6
    SEARCH = 7
    ALARM = 8
    MASTER_KEY = 9
    ITEM_CHANGE = 10
    NOTE_RESOURCE = 11
    RESOURCE_LOCAL_STATE = 12
    REVISION = 13
    MIGRATION = 14
    SMART_FILTER = 15
    COMMAND = 16
    NOTE_EMBEDDING = 17
    CONFLICT_NOTE_STATE = 18


# Human-readable note_type values stored in the database for the Joplin
# item types that the scripts care about. Types not listed map to "".
NOTE_TYPE_NAMES = {
    JoplinType.NOTE: "note",
    JoplinType.FOLDER: "folder",
    JoplinType.RESOURCE: "resource",
    JoplinType.TAG: "tag",
}
