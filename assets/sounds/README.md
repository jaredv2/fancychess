# Chess Alarm Sounds

This directory should contain the alarm sound files for the Chess Alarm app.

## Required Sound Files

### alarm.mp3 or alarm.wav

The main alarm tone that plays when an alarm is triggered. Should be:

- A loopable alarm sound (at least 1-2 seconds)
- Loud enough to wake someone from sleep
- Preferably with multiple frequency changes to avoid habituation
- Royalty-free for distribution

### beep.wav

A fallback beep tone used if the main alarm sound fails to load.

## Suggested Sources

1. **Freesound.org** - <https://freesound.org>
   - Search for "alarm", "bell", "beep"
   - Filter by "Unmodified" license to avoid attribution requirements

2. **Zapsplat** - <https://www.zapsplat.com>
   - Free sound effects library
   - No login required for download

3. **Pixabay** - <https://pixabay.com/sound-effects/>
   - High-quality royalty-free sounds

4. **Generate Programmatically**
   - Use Audacity to generate a simple sine wave beep
   - 1000 Hz sine wave, 1 second duration, 0.2 second silence pattern

## Implementation Notes

The audio service in `lib/services/audio_service.dart` will:

1. Load the primary alarm sound from `assets/sounds/alarm.mp3`
2. Fall back to `assets/sounds/beep.wav` if the primary fails
3. Loop the sound continuously
4. Ramp volume every 5 seconds until user solves puzzle

## Legal Considerations

Ensure all sound files are:

- Royalty-free
- Licensed for commercial use
- Not copyrighted material
- Attribution-free (unless you want to include attribution in the app)

Once you have obtained the sound files, place them in this directory and they will be automatically included in the app build.
