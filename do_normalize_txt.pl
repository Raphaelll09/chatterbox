#!/usr/bin/perl
use strict;

sub do_spell {
	my $s = shift(@_);
	$s=uc($s);
	$s =~ s/A/ a/g;
	$s =~ s/B/ b e/g;
	$s =~ s/C/ s e/g;
	$s =~ s/D/ d e/g;
	$s =~ s/E/ x^/g;
	$s =~ s/F/ e^ f/g;
	$s =~ s/G/ z^ e/g;
	$s =~ s/H/ a s^/g;
	$s =~ s/I/ i/g;
	$s =~ s/J/ z^ i/g;
	$s =~ s/K/ k a/g;
	$s =~ s/L/ e^ l/g;
	$s =~ s/M/ e^ m/g;
	$s =~ s/N/ e^ n/g;
	$s =~ s/O/ o/g;
	$s =~ s/P/ p e/g;
	$s =~ s/Q/ k y/g;
	$s =~ s/R/ e^ r/g;
	$s =~ s/S/ e^ s/g;
	$s =~ s/T/ t e/g;
	$s =~ s/U/ y/g;
	$s =~ s/V/ v e/g;
	$s =~ s/W/ d u b l q v e/g;
	$s =~ s/X/ i k s/g;
	$s =~ s/Y/ i g r e^ k/g;
	$s =~ s/Z/ z^ e^ d/g;
	return("{".$s."}");
}

sub do_adr {
	my $s = shift(@_);
	$s =~ s/[><]//g;
	$s =~ s/(https?)/do_spell($1)/egi;
	$s =~ s/\&/ \{e^ k o^m e^ r s j a l\} /g;
	$s =~ s/\@/ \{a r o^ b a z\} /g;
	$s =~ s/\// \{s l a s^\} /g;
	$s =~ s/\:/ \{d x p w e~\} /g;
	$s =~ s/\.(?=[^$ \n])/ \{p w e~\} /g;
	$s =~ s/\=/ \{e g a l\} /g;
	$s =~ s/\-/ \{t i r e^\} /g;
	$s =~ s/\_/ \{s u l i n~ e\} /g;
	$s =~ s/\?/ \{p w e~ d e~ t e r o g a s j o~\} /g;
	return($s);
}
my $s = "";
my $cr=1;
while ($_ = <STDIN>) {
	chomp;
	$_ =~ s/(?<=(\w)$)$/\./;
	$_ =~ s/(\.\.\.|…)/~/g;
	$_ =~ s/\%/ {p u r s a~} /g;
	$_ =~ s/(?<=\d\s?)m2(?=[ \.\?\!\:;,\/~])/ {m e^ t r} {k a r e} /g;
	$_ =~ s/(?<=\d\s?)m3(?=[ \.\?\!\:;,\/~])/ {m e^ t r} \{k y b} /g;
	$_ =~ s/(?<=\d\s?)m(?=[ \.\?\!\:;,\/~])/ {m e^ t r} /g;
	$_ =~ s/(?<=\d\s?)kms?2?(?=[ \.\?\!\:;,\/~])/ {k i l o m e^ t r} {k a r e} /g;
	$_ =~ s/(?<=\d\s?)kms?(?=[ \.\?\!\:;,\/~])/ {k i l o m e^ t r} /g;
	$_ =~ s/(?<=\d\s?)l(?=[ \.\?\!\:;,\/~])/{l i t r} /g;
	$_ =~ s/km\/h/ {k i l o m e^ t r x^ r} /g;
	$_ =~ s/n°/ \{n u m e r o\} /g;
	$_ =~ s/(?i) k[\.\-]?o\b/ \{k a o\} /g;
	$_ =~ s/(?i) we / \{w i k e^ n d\} /g;
	$_ =~ s/\/0?1\/(?=(\d{4}|\d{2}))/ janvier /g;
	$_ =~ s/\/0?2\/(?=(\d{4}|\d{2}))/ février /g;
	$_ =~ s/\/0?3\/(?=(\d{4}|\d{2}))/ mars /g;
	$_ =~ s/\/0?4\/(?=(\d{4}|\d{2}))/ avril /g;
	$_ =~ s/\/0?5\/(?=(\d{4}|\d{2}))/ mai /g;
	$_ =~ s/\/0?6\/(?=(\d{4}|\d{2}))/ juin /g;
	$_ =~ s/\/0?7\/(?=(\d{4}|\d{2}))/ juillet /g;
	$_ =~ s/\/0?8\/(?=(\d{4}|\d{2}))/ aout /g;
	$_ =~ s/\/0?9\/(?=(\d{4}|\d{2}))/ septembre /g;
	$_ =~ s/\/0?10\/(?=(\d{4}|\d{2}))/ octobre /g;
	$_ =~ s/\/0?11\/(?=(\d{4}|\d{2}))/ novembre /g;
	$_ =~ s/\/0?12\/(?=(\d{4}|\d{2}))/ décembre /g;
	$_ =~ s/(?i)N°/ numéro /g;
	$_ =~ s/(?i)(?<=[\d\s])Mo(?=\W)/ mégaoctets /ig;
	$_ =~ s/(?i)(?<=[\d]) mns?(?=\W)/ minutes /ig;
	$_ =~ s/(?i)(?<=\s)WE(?=\W)/ week-end /ig;
	$_ =~ s/(?i)(?<=\s)RDV(?=\W)/ rendez-vous /ig;
	$_ =~ s/(?<=\s)4x4(?=\W)/ {k a t k a t r} /ig;
	$_ =~ s/(?<=[\d\s])kms(?=\W)/ kilomètres /ig;
	$_ =~ s/(?i)(?<=\s)stp(?=\W)/ s'il te plait /ig;
	$_ =~ s/µ/ micro /g;	
	$_ =~ s/©/ \{k o p i r a i t\} /g;	
	$_ =~ s/c-à-d / \{c e^ t a d i r\} /g;
	$_ =~ s/€/ euros /g;
	$_ =~ s/(https?\:[^ \,]+)/do_adr($1) /egi; # web
	$_ =~ s/(www.[^ \,]+)/do_adr($1) /egi; # web
	$_ =~ s/([^ \@]+\@[\w\d]+\.[^ \,]+)/do_adr($1) /egi; # mail
	$_ =~ s/jpg([ ])/ \{z^ i p e^ g\} $1/g;
	$_ =~ s/bcp(?=\s)/ beaucoup /ig;
	$_ =~ s/Mr\.(?=\s)/ monsieur /ig;
	$_ =~ s/Mlle\.(?=\s)/ mademoiselle /ig;
	$_ =~ s/Mgr(?=\s)/ Monseigneur /ig;
	$_ =~ s/(?<=\d)\s*j(?!['\d\w])/ Nom(JOUR) /g;
	$_ =~ s/(?<=\d)\s*n(?!['\d\w])/ Nom(NUIT) /g;
	$_ =~ s/(?<=\d)\s*\*(?!['q\d\w])/  \{e t w a l\}  /g;
	$_ =~ s/(?<=\d)(?=\d{9}[ \.\?\!\:;,\/~])/ milliards /g;
	$_ =~ s/(?<=\d)(?=\d{6}[ \.\?\!\:;,\/~])/ millions /g;
	$_ =~ s/(?<=\d)(?=\d{3}[ \.\?\!\:;,\/~])/ mille /g;
	$_ =~ s/(?<=\d)(?=\d{2}[ \.\?\!\:;,\/~])/ cent /g;
	$_ =~ s/10(?=[ \.\?\!\:;,\/~])/ dix /g;
	$_ =~ s/11(?=[ \.\?\!\:;,\/~])/ onze /g;
	$_ =~ s/12(?=[ \.\?\!\:;,\/~])/ douze /g;
	$_ =~ s/13(?=[ \.\?\!\:;,\/~])/ treize /g;
	$_ =~ s/14(?=[ \.\?\!\:;,\/~])/ quatorze /g;
	$_ =~ s/15(?=[ \.\?\!\:;,\/~])/ quinze /g;
	$_ =~ s/16(?=[ \.\?\!\:;,\/~])/ seize /g;
	$_ =~ s/20?(?=\d[ \.\?\!\:;,\/~])/ vingt /g;
	$_ =~ s/30?(?=\d[ \.\?\!\:;,\/~])/ trente /g;
	$_ =~ s/40?(?=\d[ \.\?\!\:;,\/~])/ quarante /g;
	$_ =~ s/50?(?=\d[ \.\?\!\:;,\/~])/ cinquante /g;
	$_ =~ s/60?(?=\d[ \.\?\!\:;,\/~])/ soixante /g;
	$_ =~ s/70?(?=\d[ \.\?\!\:;,\/~])/ soixante-dix /g;
	$_ =~ s/80?(?=\d[ \.\?\!\:;,\/~])/ quatre-vingt/g;
	$_ =~ s/90?(?=\d[ \.\?\!\:;,\/~])/ quatre-vingt-dix/g;
	$_ =~ s/0//g;
	$_ =~ s/1/ un /g;
	$_ =~ s/2/ deux /g;
	$_ =~ s/3/ trois /g;
	$_ =~ s/4/ quatre /g;
	$_ =~ s/5/ cinq /g;
	$_ =~ s/6/ six /g;
	$_ =~ s/7/ sept /g;
	$_ =~ s/8/ huit /g;
	$_ =~ s/9/ neuf /g;
	$_ =~ s/ +(?=[!?,\.])//g;
	$_ =~ s/ +/ /g;

	# # erreurs de phonétisation systématiques
	# $_ =~ s/ super/ {s y p e^ r}/g;
	# $_ =~ s/ billes+ / {b i j} /g;
	# $_ =~ s/ Sherlock / {s^ e r l o^ k}/g;
	# $_ =~ s/ Holmes / {o^ l m s q}/g;
	
  print $_."\n";
}

