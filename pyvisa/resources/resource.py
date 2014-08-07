# -*- coding: utf-8 -*-
"""
    pyvisa.resources.resource
    ~~~~~~~~~~~~~~~~~~~~~~~~~

    High level wrapper for a Resource.

    This file is part of PyVISA.

    :copyright: 2014 by PyVISA Authors, see AUTHORS for more details.
    :license: MIT, see LICENSE for more details.
"""

from __future__ import division, unicode_literals, print_function, absolute_import

import math
import time

from .. import constants
from .. import errors
from .. import logger
from .. import highlevel

from . import helpers as hlp


class Resource(object):
    """Base class for resources.

    Do not instantiate directly, use :meth:`pyvisa.highlevel.ResourceManager.open`.

    :param resource_manager: A resource manager instance.
    :param resource_name: the VISA name for the resource (eg. "GPIB::10")
    """

    @classmethod
    def register(cls, interface_type, resource_class):
        def _internal(python_class):
            highlevel.ResourceManager.resource_classes[(interface_type, resource_class)] = python_class
            return python_class
        return _internal

    def __init__(self, resource_manager, resource_name):
        self._resource_manager = resource_manager
        self.visalib = self._resource_manager.visalib
        self._resource_name = resource_name

        self._logging_extra = {'library_path': self.visalib.library_path,
                               'resource_manager.session': self._resource_manager.session,
                               'resource_name': self._resource_name,
                               'session': None}

        #: Session handle.
        self.session = None

    def __del__(self):
        self.close()

    def __str__(self):
        return "%s at %s" % (self.__class__.__name__, self.resource_name)

    def __repr__(self):
        return "<%r(%r)>" % (self.__class__.__name__, self.resource_name)

    @property
    def last_status(self):
        return self.visalib.get_last_status_in_session(self.session)

    @property
    def timeout(self):
        """The timeout in milliseconds for all resource I/O operations.
        """
        timeout = self.get_visa_attribute(constants.VI_ATTR_TMO_VALUE)
        if timeout == constants.VI_TMO_INFINITE:
            return float('+nan')
        return timeout

    @timeout.setter
    def timeout(self, timeout):
        if timeout < 0 or math.isnan(timeout):
            timeout = constants.VI_TMO_INFINITE
        elif not (0 <= timeout <= 4294967294):
            raise ValueError("timeout value is invalid")
        else:
            timeout = int(timeout)
        self.set_visa_attribute(constants.VI_ATTR_TMO_VALUE, timeout)

    @property
    def resource_info(self):
        return self.visalib.parse_resource_extended(self._resource_manager.session, self.resource_name)

    @property
    def resource_class(self):
        """The resource class of the resource as a string.
        """

        try:
            return self.get_visa_attribute(constants.VI_ATTR_RSRC_CLASS).upper()
        except errors.VisaIOError as error:
            if error.error_code != constants.VI_ERROR_NSUP_ATTR:
                raise
        return 'Unknown'

    resource_name = hlp.attr('VI_ATTR_RSRC_NAME',
                             'The VISA resource name of the resource as a string.',
                             ro=True)

    @property
    def interface_type(self):
        """The interface type of the resource as a number.
        """
        return self.visalib.parse_resource(self._resource_manager.session,
                                           self.resource_name).interface_type

    _d_ = 'Current locking state of the resource.\n\n' \
          'The resource can be unlocked, locked with an exclusive lock, or locked with a shared lock.'
    lock_state = hlp.enum_attr('VI_ATTR_RSRC_LOCK_STATE', constants.AccessModes, doc=_d_, ro=True)

    _d_ = 'Specifies the board number for the given interface.'
    interface_number = hlp.range_attr('VI_ATTR_INTF_NUM', 0, 65535, doc=_d_, ro=True)

    del _d_

    def open(self, access_mode=constants.AccessModes.no_lock, open_timeout=5000):
        """Opens a session to the specified resource.

        :param access_mode: Specifies the mode by which the resource is to be accessed.
        :type access_mode: :class:`pyvisa.constants.AccessMode.NoLock`
        :param open_timeout: Milliseconds before the open operation times out.
        :type open_timeout: int
        """

        logger.debug('%s - opening ...', self._resource_name, extra=self._logging_extra)
        with self.visalib.ignore_warning(constants.VI_SUCCESS_DEV_NPRESENT):
            self.session, status = self._resource_manager.open_bare_resource(self._resource_name, access_mode, open_timeout)

            if status == constants.VI_SUCCESS_DEV_NPRESENT:
                # The device was not ready when we opened the session.
                # Now it gets five seconds more to become ready.
                # Every 0.1 seconds we probe it with viClear.
                start_time = time.time()
                sleep_time = 0.1
                try_time = 5
                while time.time() - start_time < try_time:
                    time.sleep(sleep_time)
                    try:
                        self.clear()
                        break
                    except errors.VisaIOError as error:
                        if error.error_code != constants.VI_ERROR_NLISTENERS:
                            raise

        self._logging_extra['session'] = self.session
        logger.debug('%s - is open with session %s',
                     self._resource_name, self.session,
                     extra=self._logging_extra)

    def before_close(self):
        """Called just before closing an instrument.
        """
        pass

    def close(self):
        """Closes the VISA session and marks the handle as invalid.
        """
        if self._resource_manager.session is None or self.session is None:
            return

        logger.debug('%s - closing', self._resource_name,
                     extra=self._logging_extra)
        self.before_close()
        self.visalib.close(self.session)
        logger.debug('%s - is closed', self._resource_name,
                     extra=self._logging_extra)
        self.session = None

    def get_visa_attribute(self, name):
        """Retrieves the state of an attribute in this resource.

        :param name: Resource attribute for which the state query is made (see Attributes.*)
        :return: The state of the queried attribute for a specified resource.
        :rtype: unicode (Py2) or str (Py3), list or other type
        """
        return self.visalib.get_attribute(self.session, name)[0]

    def set_visa_attribute(self, name, state):
        """Sets the state of an attribute.

        :param name: Attribute for which the state is to be modified. (Attributes.*)
        :param state: The state of the attribute to be set for the specified object.
        """
        self.visalib.set_attribute(self.session, name, state)

    def clear(self):
        """Clears this resource
        """
        self.visalib.clear(self.session)

    def install_handler(self, event_type, handler, user_handle=None):
        """Installs handlers for event callbacks in this resource.

        :param event_type: Logical event identifier.
        :param handler: Interpreted as a valid reference to a handler to be installed by a client application.
        :param user_handle: A value specified by an application that can be used for identifying handlers
                            uniquely for an event type.
        :returns: user handle (a ctypes object)
        """

        return self.visalib.install_handler(self.session, event_type, handler, user_handle)[:-1]

    def uninstall_handler(self, event_type, handler, user_handle=None):
        """Uninstalls handlers for events in this resource.

        :param event_type: Logical event identifier.
        :param handler: Interpreted as a valid reference to a handler to be uninstalled by a client application.
        :param user_handle: A value specified by an application that can be used for identifying handlers
                            uniquely in a session for an event.
        """

        self.visalib.uninstall_handler(self.session, event_type, handler, user_handle)

    def lock(self, timeout=None, requested_key=None):
        """Establish a shared lock to the resource.

        :param timeout: Absolute time period (in milliseconds) that a resource
                        waits to get unlocked by the locking session before
                        returning an error. (Defaults to self.timeout)
        :param requested_key: Access key used by another session with which you
                              want your session to share a lock or None to generate
                              a new shared access key.
        :returns: A new shared access key if requested_key is None,
                  otherwise, same value as the requested_key
        """
        timeout = self.timeout if timeout is None else timeout
        return self.visalib.lock(self.session, constants.AccessModes.shared_lock, timeout, requested_key)[0]

    def unlock(self):
        """Relinquishes a lock for the specified resource.
        """
        self.visalib.unlock(self.session)