$(document).ready(function(){
	// 마우스 오버시 토글
	$('#header').hover(function(){
		$(this).toggleClass('ons')
	});
	
	$('.pcGnb > ul > li').mouseover(function(){
	$(this).children('ul').stop().slideDown();
	});

	// 마우스 아웃시 닫기
	$('.pcGnb > ul > li').mouseout(function(){
	$(this).children('ul').stop().slideUp();
	});
	
	$('.menuToggle').click(function(){
		$(this).toggleClass('on');
		$('body').toggleClass('on');
		$('#header').toggleClass('onss');
		$('.mo_bg').toggleClass('on');
		$('.moGnb').toggleClass('on');
	});
	
	$('.mo_bg').click(function(){
		$('.menuToggle').removeClass('on');
		$('body').removeClass('on');
		$('#header').removeClass('onss');
		$('.mo_bg').removeClass('on');
		$('.moGnb').removeClass('on');
	});
	
	$('.moGnb > ul > li').click(function(){
		$(this).toggleClass('on');
		$(this).children('ul').stop().slideToggle();
	});
	

});