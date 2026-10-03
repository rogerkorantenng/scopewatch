# Scopewatch narration script

Three acts, matching the video:

| Act | Screen | Target |
|---|---|---|
| 1 | Presentation slides — the problem, with numbers | ~60 s |
| 2 | The live app — real surgery, measured | ~95 s |
| 3 | Presentation slide — limitations and what is next | ~30 s |

Voice: calm and clinical, the register of someone reading a measurement out loud.
Words spelled for the voice: "millilitres", never "ml"; "per cent", never "%".
Shot cues: `narration-cues.md`.

Nothing above the rule below is spoken.

---

## ACT 1 — slides

Hi, I'm Roger, and I'll be presenting Scopewatch for the OpenCV AI Competition.
Scopewatch reads the laparoscopic camera already in the operating room and measures
how much of the surgical field is covered in blood — or says plainly when it cannot.

In the United States, postpartum haemorrhage causes about eleven per cent of maternal
deaths, and it is the leading cause of death on the day a baby is born.

California reviews every one of those deaths. Across two point four million births, an
expert panel judged sixty three per cent of haemorrhage deaths highly preventable — and
the factor they found in seventy two per cent of cases was delayed recognition.
Somebody did not see it in time.

The American College of Obstetricians and Gynecologists names the same cause. Imprecise
estimation of how much blood a patient has actually lost is, in their words, a leading
cause of delayed response to haemorrhage.

Measured against haematocrit, visual estimation underestimated the loss in ninety per
cent of cases. A fifth of those patients had lost over a litre — and by eye, none of
them had haemorrhaged at all.

The same shape appears in surgery: across five hundred and forty eight recorded
gallbladder operations, the safety step that prevents bile duct injury was recorded in
sixty one per cent of cases.

In all of these, the information was already in front of a camera already in the room,
and a person under time pressure was asked to judge it by eye.

Scopewatch measures it instead. On clips held out from tuning, sixty four per cent of
the pixels it calls blood are blood. Across all fifteen laparoscopic clips, seventy
eight per cent.

And when it cannot measure something, it says so by name rather than printing a number
it cannot stand behind.

## ACT 2 — the live app

This is a laparoscopic repair of a bleeding ulcer, openly licensed. Ninety three
seconds of real surgery, analysed in about thirty.

The blood-covered field peaks at about twenty five per cent. Every pixel behind that
number came from the picture.

A pixel is blood when it clears three tests at once: enough colour in absolute terms,
enough colour for its own lightness, and a hue inside a band around the scene. Darkness
is never evidence, because a laparoscope's light sits at the tip and every frame is
darker at its edge.

Here is the field trace across the whole case — every frame that passed the quality
gates, with marks where measurement was suspended and why.

Now the volume row. It reads cannot measure. Scale comes from an instrument shaft of
known diameter, and on real video that width shifts by twenty nine to sixty one per
cent inside one clip, because every instrument sits at its own distance from the lens.
So it prints no figure, and names the gate that stopped it.

This is the evidence behind the numbers — every frame the product kept, so any figure
on this page traces back to the picture it came from. Five hundred and thirty six of
five hundred and sixty one frames were measurable, and the rest are listed with their
reason.

Here is open surgery, which Scopewatch was not built for. It
refuses it outright, by name, as out of domain, rather than measuring it anyway.

The shadow at the rim of the scope's circle reads zero, and the inside of a port
sleeve one point four per cent. Both were counted as blood by the first version, and
both are pinned now by tests on real frames.

The pipeline is OpenCV five, pinned, because an unpinned install resolves to four point
fourteen and silently fails the requirement. It runs on Amazon App Runner.

We also trained a learned segmenter to replace the colour rule — MobileNetV3 with an
FPN decoder, exported to ONNX and run through that same OpenCV path. On the held-out
frames it reached six per cent. The colour rule reached sixty four. On a corpus this
size the classical method wins, and that is what ships.

## ACT 3 — closing slide

Scopewatch is tuned to be right when it marks something, so some blood is left
unmarked. No clip here passes the scale gate, so it shows no millilitres, and the
bleeding alarm does not fire on a moving laparoscope.

What comes next is data, not modelling. Each labelled operation we add raises held-out
precision by about three and a half points.

It is a measurement instrument, not a medical device, and it takes no clinical action.
