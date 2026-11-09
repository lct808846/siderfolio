set datafile separator comma
set datafile missing "nan"
set encoding utf8

set terminal pngcairo size 1600,1200 font "DejaVu Sans,14"
set output "/output/figure.png"
set title "x vs y 散点图"
set xlabel "x（无单位）"
set ylabel "y（无单位）"
set grid
set key top left
set autoscale
plot "/input/data.csv" using 1:2 with points pt 7 ps 1.5 lc rgb "#1f77b4" title "data.csv: x-y 观测点"
unset output

set terminal pdfcairo size 8,6 font "DejaVu Sans,12"
set output "/output/figure.pdf"
set title "x vs y 散点图"
set xlabel "x（无单位）"
set ylabel "y（无单位）"
set grid
set key top left
set autoscale
plot "/input/data.csv" using 1:2 with points pt 7 ps 1.5 lc rgb "#1f77b4" title "data.csv: x-y 观测点"
unset output