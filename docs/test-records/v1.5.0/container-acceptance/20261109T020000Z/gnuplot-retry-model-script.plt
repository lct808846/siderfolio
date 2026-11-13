set datafile separator comma
set encoding utf8
set terminal pngcairo size 1200,900 font "WenQuanYi Zen Hei,14"
set output "/output/figure.png"
set title "x 与 y 散点图" font "WenQuanYi Zen Hei,18"
set xlabel "x（无单位）" font "WenQuanYi Zen Hei,14"
set ylabel "y（无单位）" font "WenQuanYi Zen Hei,14"
set key top left font "WenQuanYi Zen Hei,12"
set grid
set border 3
set tics nomirror
set style data points
plot "/input/data.csv" using 1:2 with points pt 7 ps 1.6 lc rgb "#1f4e9c" title "数据点"
unset output
set terminal pdfcairo size 12,9 font "WenQuanYi Zen Hei,14"
set output "/output/figure.pdf"
replot
unset output