set datafile separator comma
set encoding utf8

# 字体：优先 WenQuanYi Zen Hei，缺失时回退默认
font_cn = "WenQuanYi Zen Hei"
if (system("fc-list : family | grep -c 'WenQuanYi Zen Hei'") ne "0") {
    set term pngcairo font font_cn,14 size 1600,1200
} else {
    set term pngcairo font ",14" size 1600,1200
}
set output "/output/figure.png"
set title "x 与 y 散点图"
set xlabel "x（无单位）"
set ylabel "y（无单位）"
set grid
set key top left
set autoscale
plot "/input/data.csv" using 1:2 with points pt 7 ps 1.5 lc rgb "#1f77b4" title "数据点"
unset output

if (system("fc-list : family | grep -c 'WenQuanYi Zen Hei'") ne "0") {
    set term pdfcairo font font_cn,12 size 8,6
} else {
    set term pdfcairo font ",12" size 8,6
}
set output "/output/figure.pdf"
replot
unset output