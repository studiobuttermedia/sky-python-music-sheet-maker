#import json, re
import os
from skymusic.resources import Resources
from io import BytesIO
from skymusic.parsers import music_theory
from skymusic.modes import InputMode
try:
    import mido
    no_mido_module = False
except (ImportError, ModuleNotFoundError):
    no_mido_module = True

class MidiSongParser:
    """
    For parsing a text format into a Song object
    """

    def __init__(self, maker, silent_warnings=True):
        self.maker = maker
        self.silent_warnings = silent_warnings
        self.note_parser = InputMode.MIDI.get_note_parser()
        self.music_theory = music_theory.MusicTheory(self)
        
        root_note = self.note_parser.convert_chromatic_position_into_note_name(0)
        root_note = self.note_parser.english_note_name(root_note)
        self.root_pitch = Resources.MIDI_PITCHES[root_note]
                
    def detect_midi(self, song_line, strict=False):
        if isinstance(song_line, (list,tuple)):
            midi_bytes = song_line[0]
        else:
            midi_bytes = song_line
        try:
            if midi_bytes.startswith(b'MThd'):
                return True
            else:
                return False #Non-midi binary file
        except TypeError:
            if not strict and midi_bytes.startswith('MThd'): #Accepting string
                return True
            else:
                return False
        except AttributeError: #Neither string or bytes, skipping
            return False
    
    def extract_note_interval(self, track, min_interval):
        
        times = []
        t = 0
        '''
        for i, msg in enumerate(track):
            try:
                t += msg.time
            except AttributeError:
                pass
            if msg.type == 'note_on':
                t2 = 0
                for msg2 in track[i:]:
                    try:
                        t2 += msg2.time
                    except AttributeError:
                        pass
                    if msg2.type == 'note_off':
                        if msg2.note == msg.note:
                            times.append(t+t2)
                            break
        '''
        i = 0
        for msg in track:
            if i > 128:
                break
            if msg.type == 'note_on':
                if msg.velocity != 0: #reject  silences
                    times.append(t)
                    i += 1
            try:
                t += msg.time
            except AttributeError:
                pass
                
        if len(times) == 0:
            return None
        
        #print('%%note_on DIFFS')
        #diffs = [times[i] - times[i-1] for i in range(1, len(times))]
        #print(diffs)
        
        intervals = [interval for interval in self.music_theory.analyze_tempo(times, min_interval) if interval > 2*min_interval]
        
        if len(intervals) > 0:
            note_interval = intervals[0]
        else:
            note_interval = None
            
        return note_interval
    
    def has_notes(self, track):
        
        return any([not msg.is_meta for msg in track])

    def extract_key(self, track):
        
        for msg in track:
            if msg.type == 'key_signature':
                return msg.key
        
        return None
 
    def extract_first_key(self, midi_file):
        
        if midi_file:
            for track in midi_file.tracks:
                track_key = self.extract_key(track)
                if track_key:
                    return track_key
        
        return None
                    
    def extract_lowest_octave(self, track):
        
        lowest = 128
        for msg in track:
            if msg.type == 'note_on':
                if msg.note < lowest:
                    lowest = msg.note
                    
        lowest_octave = int((lowest - self.root_pitch) / 12)
        
        return lowest_octave

    def parse_meta(self, track):
        
        metadata = []
        if track.name:
            metadata.append(Resources.LYRIC_DELIMITER + 'Track name: ' + track.name)
        
        if self.has_notes(track):
            track_key = self.extract_key(track)
            if track_key:
                metadata.append(Resources.LYRIC_DELIMITER + 'Track key: ' + track_key)
        
        return metadata
    
    def parse_first_meta(self, midi_file):
        
        metadata = []
        
        basename = ''
        if midi_file.filename:
            (basename,_) = os.path.splitext(midi_file.filename)
        metadata.append(Resources.METADATA_DELIMITER + 'Title:' + basename.capitalize())
        metadata.append(Resources.METADATA_DELIMITER + 'Artist:' + '')
        metadata.append(Resources.METADATA_DELIMITER + 'Transcript writer:' + '')
        
        first_key = self.extract_first_key(midi_file)
        
        if first_key:
            metadata.append(Resources.METADATA_DELIMITER + 'Musical key: ' + first_key)
        
        return metadata


    def parse_note_msg(self, note_msg, base_octave):
        
        if note_msg.velocity == 0:
            if note_msg.time == 0:
                return ''
            else:
                return Resources.PAUSE

        octave = int((note_msg.note - self.root_pitch) / 12)
        semi = (note_msg.note - self.root_pitch) % 12
        
        try:
            note = self.note_parser.convert_chromatic_position_into_note_name(semi)
        except KeyError:
            note = Resources.BROKEN_HARP
            
        return note + str(octave-base_octave+Resources.PARSING_START_OCTAVE)
    
    def parse_notes(self, track, note_interval):
        
        base_octave = self.extract_lowest_octave(track)
        
        notes = ['']
        t = 0
        prev_t = -note_interval
        prev_prev_t = prev_t
        for msg in track:
            try:
                t += msg.time
            except AttributeError:
                pass
            if msg.type == 'note_on':
                
                dt = t - prev_t
                
                notes += [Resources.PAUSE]*int(dt/note_interval - 1) #parses implicit silences
                
                note = self.parse_note_msg(msg, base_octave)
                
                #print(msg)
                #print(f"dt={dt:.1f}, note={note}\n")  
                
                if note == Resources.PAUSE:
                    if dt > 0.5*note_interval:
                        notes.append(note)
                      
                elif note:
                    
                    if notes[-1] == Resources.PAUSE:
                        if (t - prev_prev_t < note_interval):
                            del(notes[-1])
                        notes.append(note)
                    else:
                        if dt == 0: #chord
                            notes[-1] += note
                        elif (dt <= 0.45*note_interval) and (notes[-1] != Resources.PAUSE):
                            notes[-1] += Resources.QUAVER_DELIMITER + note
                        else:
                            notes.append(note)
                  
                if note:
                    prev_prev_t = prev_t
                    prev_t = t
                
        return ' '.join(filter(None,notes))                

    def sanitize_midi_lines(self, midi_lines):
        
        try:
            midi_bytes = b''.join(midi_lines)
        except TypeError:
            midi_bytes = ''.join(midi_lines).encode()

        return midi_bytes                                                      

    def create_MidiFile(self, midi_lines):
        
        if no_mido_module:
            print("\n***ERROR: MIDI could not be imported because mido module was not found.")
            return None
        
        midi_bytes = self.sanitize_midi_lines(midi_lines)
        
        buffer = BytesIO()
        buffer.write(midi_bytes)
        buffer.seek(0)
        
        try:
            mid = mido.MidiFile(file=buffer)
        except (IOError, EOFError):
            print("\n***ERROR: mido could not detect your file as being midi.")
            return None
        
        return mid 

    def find_key(self, midi_lines):
        
        mid = self.create_MidiFile(midi_lines)
        song_key = self.extract_first_key(mid)
        
        return [song_key] if song_key else []
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               
    
    def collect_notes(self, midi_lines):
        
        mid = self.create_MidiFile(midi_lines)
        
        if mid:
            song = []
            for track in mid.tracks:
                for msg in track:
                    if msg.type == 'note_on':
                        note = self.parse_note_msg(msg, 1)
                        if note:
                            song.append(note)
            
            return [' '.join(song)]
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  
    def parse_midi(self, midi_lines):
        
        if no_mido_module:
            return []
        
        mid = self.create_MidiFile(midi_lines)
        
        if not mid:
            return []
        
        song = self.parse_first_meta(mid)
        
        for i, track in enumerate(mid.tracks):
            
            metadata = self.parse_meta(track)
            
            note_interval = self.extract_note_interval(track, 1)
            
            #print(note_interval)
            
            if note_interval is not None:          
                notes = self.parse_notes(track, note_interval)
            else:
                notes = ''
         
            song += metadata + [notes]
            
        song = list(filter(None,song))
        return song
