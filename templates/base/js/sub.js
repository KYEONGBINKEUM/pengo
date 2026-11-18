var subFunc = (function($){
	var _snb = function(level1, level2){

		var sub_dep1=$('.sub_menu_wrap .m_1dep_box .menu'+level1);
		var sub_dep2=$('.sub_menu_wrap .m_2dep_box .menu'+level2);
		var sub_dep1_t = $(sub_dep1).text();
		var sub_dep2_t = $(sub_dep2).text();

		$('.s_visual').css({"background-image":"url(/images/sub/s_visual"+level1+".jpg)"});

		$('span.vis_dep01').text(sub_dep1_t);
		$('span.vis_dep02').text(sub_dep2_t);

		sub_dep1.addClass('on');
		sub_dep2.addClass('on');
		sub_dep2.parent().addClass('s_on');

		$('.sub_menu_wrap .m_dep_tit').click(function(){
			if($(this).hasClass('m_on')){
				$(this).removeClass('m_on');
				$(this).siblings("ul.smenu").slideUp();
			} else {
				$(this).addClass('m_on');
				$(this).siblings("ul.smenu").slideDown();
			}
		});

		$(".sub_menu_wrap .m_dep_box").on("mouseleave", function(){
			if($(this).children(".m_dep_tit").hasClass("m_on")){
				$(this).children(".m_dep_tit").removeClass("m_on");
				$(this).children("ul.smenu").slideUp(300);
			}
		});

		$(window).resize(function(){
			var width = parseInt($(this).width()); //parseint는 정수로 하기 위함
			if(width <= 976){
				$('.sub_menu_wrap .m_2dep_box .smenu').css({'display':'none'});
			}else{
				$('.sub_menu_wrap .m_2dep_box .smenu').css({'display':'flex'});
			}
		}).resize();


	};
	return{
		snb:_snb
	}
})(jQuery);



$(document).ready(function() {

	$('#tabMenu a').click(function () {
		$('html, body').animate({
		  scrollTop: $($.attr(this, 'href')).offset().top
		}, 500);
		return false;
	  });

});