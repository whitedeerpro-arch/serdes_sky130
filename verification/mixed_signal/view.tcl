# Optional GTKWave startup view. 1 UI = 250 ps; time arguments are fs.
gtkwave::/Time/Zoom/Zoom_Full
gtkwave::setNamedMarker A 24000000 "96UI payload starts"
gtkwave::setNamedMarker B 28653027 "first payload word"
gtkwave::setNamedMarker C 47687089 "last control update"
puts "REVIEW_SIGNALS [llength [gtkwave::getDisplayedSignals]]"
puts "REVIEW_MAX_TIME [gtkwave::getMaxTime]"
puts "REVIEW_ZOOM [gtkwave::getZoomFactor]"
