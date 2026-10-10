/**
 * Editor script for trial-knowledge/claim-card. Rendering is server-side
 * (TK_Blocks), so the editor preview always matches the published output.
 */
import { registerBlockType } from '@wordpress/blocks';
import { InspectorControls, useBlockProps } from '@wordpress/block-editor';
import { PanelBody, RangeControl, TextControl } from '@wordpress/components';
import ServerSideRender from '@wordpress/server-side-render';
import { __ } from '@wordpress/i18n';
import metadata from './block.json';

registerBlockType(metadata.name, {
	edit({ attributes, setAttributes }) {
		const blockProps = useBlockProps();
		return (
			<div {...blockProps}>
				<InspectorControls>
					<PanelBody title={__('הגדרות', 'trial-knowledge')}>
						<TextControl __nextHasNoMarginBottom label={__('מזהה טענה (UUID)', 'trial-knowledge')} value={attributes.claimId} onChange={(v) => setAttributes({ claimId: v.trim() })} /><RangeControl label={__('רמת כותרת', 'trial-knowledge')} min={2} max={4} value={attributes.headingLevel} onChange={(v) => setAttributes({ headingLevel: v })} />
					</PanelBody>
				</InspectorControls>
				<ServerSideRender block={metadata.name} attributes={attributes} />
			</div>
		);
	},
	save: () => null,
});
