#!/usr/bin/env python

import sys

import gi
gi.require_version('Gst', '1.0')

from gi.repository import GObject, Gst, GLib


def bus_call(bus, message, loop):
    t = message.type
    if t == Gst.MessageType.EOS:
        sys.stdout.write("End-of-stream\n")
        loop.quit()
    elif t == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        sys.stderr.write("Error: %s: %s\n" % (err, debug))
        loop.quit()
    return True


def is_raw_audio(caps):
    structure = caps.get_structure(0)
    return structure.has_name('audio/x-raw')


def is_mpegts(caps):
    structure = caps.get_structure(0)
    return structure.has_name('video/mpegts')


def is_video(caps):
    structure = caps.get_structure(0)
    return structure.get_name().startswith("video/")


def is_audio(caps):
    structure = caps.get_structure(0)
    return structure.get_name().startswith("audio/")


class GstAppContext:
    def __init__(self, uri_or_filepath):
        self.pipeline = Gst.Pipeline.new()

        # uridecodebin will decode everything, provided we have the
        # required plugins, and will output the decoded data to us
        uridecodebin = Gst.ElementFactory.make("uridecodebin", None)
        if not uridecodebin:
            sys.stderr.write("'uridecodebin' gstreamer plugin missing\n")
            sys.exit(1)
        self.pipeline.add(uridecodebin)

        # take the commandline argument and ensure that it is a uri
        if Gst.uri_is_valid(uri_or_filepath):
            uri = uri_or_filepath
        else:
            uri = Gst.filename_to_uri(uri_or_filepath)
        uridecodebin.set_property('uri', uri)

        # whenever decodebin has a new stream it will add a pad.
        # So we have to catch this event and link the pad dynamically
        # to receive the data.
        uridecodebin.connect('pad-added', self.decodebin_pad_added, self)

        # Get notified of new elements used by uridecodebin for decoding
        # We use this to set useful properties/configs to those elements
        uridecodebin.connect('element-added', self.decodebin_element_added,
                             None)

        # With this we control what we want decodebin to keep decoding or not
        # so that we save processing on what we don't need (we don't need
        # video decoding here)
        uridecodebin.connect('autoplug-continue',
                             self.decodebin_autoplug_continue, None)

        # create and event loop and feed gstreamer bus mesages to it
        self.loop = GLib.MainLoop()

        bus = self.pipeline.get_bus()
        bus.add_signal_watch()

        # Callback to get notified of errors or end-of-stream so we
        # finish the application
        bus.connect("message", bus_call, self.loop)

    def connect_to_audio_transcoding(self, pad):
        pipeline = self.pipeline

        # We want the following linked to this new pad:
        # queue ! audioconvert ! audiorate ! audioresample ! flacenc ! queue !
        # appsink
        #
        # The audio* are converters to ensure that we can deliver audio in the
        # format that flacenc expects in case the decoded audio is not
        # compatible. They will only convert if required, otherwise it is pass
        # through. Flacenc will encode and handle the data to appsink, which
        # will call a function that we provide so the application has access
        # to the data.

        queue = Gst.ElementFactory.make('queue', None)
        audioconvert = Gst.ElementFactory.make('audioconvert', None)
        audiorate = Gst.ElementFactory.make('audiorate', None)
        audioresample = Gst.ElementFactory.make('audioresample', None)
        flacenc = Gst.ElementFactory.make('flacenc', None)
        queue2 = Gst.ElementFactory.make('queue', None)
        appsink = Gst.ElementFactory.make('appsink', None)
        pipeline.add(queue)
        pipeline.add(audioconvert)
        pipeline.add(audiorate)
        pipeline.add(audioresample)
        pipeline.add(flacenc)
        pipeline.add(queue2)
        pipeline.add(appsink)

        # Set our callbacks to appsink
        appsink.set_property('emit-signals', True)
        appsink.connect('new-sample', self.new_sample, None)
        appsink.connect('eos', self.eos, None)

        # TODO check result
        queue.link(audioconvert)
        audioconvert.link(audiorate)
        audiorate.link(audioresample)
        audioresample.link(flacenc)
        flacenc.link(queue2)
        queue2.link(appsink)

        pad.link(queue.get_static_pad('sink'))

        appsink.sync_state_with_parent()
        queue2.sync_state_with_parent()
        flacenc.sync_state_with_parent()
        audioresample.sync_state_with_parent()
        audiorate.sync_state_with_parent()
        audioconvert.sync_state_with_parent()
        queue.sync_state_with_parent()

    def decodebin_element_added(self, decodebin, element, data):
        factory = element.get_factory()
        elementtype = factory.get_element_type()

        # uridecodebin uses a decodebin internally, so we want also to be
        # notified of decodebin's internal elements
        if elementtype.name == 'GstDecodeBin':
            element.connect('element-added', self.decodebin_element_added,
                            None)

        # Set mpegts demuxer to preserve the original timestamps on
        # buffers
        elif elementtype.name == 'GstTSDemux':
            element.set_property('preserve-mpegts-timestamps', True)

        return True

    def decodebin_autoplug_continue(self, decodebin, pad, caps, data):
        if is_mpegts(caps):
            return True
        if is_video(caps):
            return False
        if is_audio(caps):
            return True

        return False

    def connect_to_fakesink(self, pad):
        fakesink = Gst.ElementFactory.make('fakesink', None)
        self.pipeline.add(fakesink)

        # TODO check result
        pad.link(fakesink.get_static_pad('sink'))
        fakesink.sync_state_with_parent()

    def decodebin_pad_added(self, decodebin, pad, data=None):
        caps = pad.get_current_caps()
        # We got a new pad, if it contains raw audio we want to transcode
        # and capture the data. Otherwise we connect to a fakesink (just
        # discards it)
        if is_raw_audio(caps):
            self.connect_to_audio_transcoding(pad)
        else:
            self.connect_to_fakesink(pad)

    def new_sample(self, appsink, data=None):
        sample = appsink.emit('pull-sample')
        gstbuffer = sample.get_buffer()

        try:
            pts = gstbuffer.pts
            (result, mapinfo) = gstbuffer.map(Gst.MapFlags.READ)
            data = mapinfo.data
            size = mapinfo.size
            print(pts, size, data[0], gstbuffer.get_flags())

        finally:
            gstbuffer.unmap(mapinfo)

        return Gst.FlowReturn.OK

    def eos(self, appsink, data=None):
        print("Appsink EOS")


def main(args):
    if len(args) != 2:
        sys.stderr.write("usage: %s <media file or uri>\n" % args[0])
        sys.exit(1)

    Gst.init(None)
    gstapp = GstAppContext(args[1])

    # start play back and listed to events
    gstapp.pipeline.set_state(Gst.State.PLAYING)
    try:
        gstapp.loop.run()
    except:
        pass

    # cleanup
    gstapp.pipeline.set_state(Gst.State.NULL)


if __name__ == '__main__':
    sys.exit(main(sys.argv))
